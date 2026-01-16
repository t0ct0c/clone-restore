"""
AWS EC2 Provisioning Module

Handles ephemeral WordPress target provisioning on EC2 Auto Scaling with Docker.
"""

import logging
import time
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, Dict
import boto3
import paramiko
from botocore.exceptions import ClientError


logger = logging.getLogger(__name__)


class EC2Provisioner:
    """Provision ephemeral WordPress targets on EC2 with Docker"""
    
    def __init__(self, region: str = 'us-east-1'):
        self.ec2_client = boto3.client('ec2', region_name=region)
        self.asg_client = boto3.client('autoscaling', region_name=region)
        self.cloudwatch_client = boto3.client('cloudwatch', region_name=region)
        self.region = region
        
        # Configuration (should be environment variables in production)
        self.asg_name = 'wp-targets-asg'
        self.docker_image = '044514005641.dkr.ecr.us-east-1.amazonaws.com/wordpress-target-sqlite:latest'
        self.alb_dns = 'wp-targets-alb-1392351630.us-east-1.elb.amazonaws.com'
        self.ssh_key_path = '/app/ssh/wp-targets-key.pem'
        self.port_range_start = 8001
        self.port_range_end = 8010
    
    def provision_target(self, customer_id: str, ttl_minutes: int = 30) -> Dict:
        """
        Provision ephemeral WordPress target
        
        Args:
            customer_id: Unique customer identifier
            ttl_minutes: Time-to-live in minutes
        
        Returns:
            Dict with target details
        """
        try:
            logger.info(f"Provisioning target for customer {customer_id}")
            
            # 1. Find least-loaded EC2 instance
            instance = self._find_least_loaded_instance()
            if not instance:
                logger.error("No available EC2 instances")
                return {
                    'success': False,
                    'error_code': 'NO_CAPACITY',
                    'message': 'No available EC2 instances'
                }
            
            instance_id = instance['InstanceId']
            # Use private IP for inter-VPC communication
            instance_ip = instance.get('PrivateIpAddress')
            public_ip = instance.get('PublicIpAddress')
            
            logger.info(f"Using instance {instance_id} at {instance_ip} (public: {public_ip})")
            
            # 2. Allocate port for container
            port = self._allocate_port(instance_ip)
            if not port:
                logger.error("No available ports on instance")
                return {
                    'success': False,
                    'error_code': 'PORT_EXHAUSTED',
                    'message': 'Instance at capacity, scaling up...'
                }
            
            # 3. Generate WordPress credentials
            wp_password = self._generate_password()
            
            # 4. Start Docker container via SSH
            container_started = self._start_container(
                instance_ip,
                customer_id,
                port,
                wp_password
            )
            
            if not container_started:
                return {
                    'success': False,
                    'error_code': 'CONTAINER_START_FAILED',
                    'message': 'Failed to start Docker container'
                }
            
            # 5. Activate plugin and get API key directly (Bypass Browser)
            logger.info(f"Activating plugin directly in container {customer_id}...")
            api_key = self._activate_plugin_directly(instance_ip, customer_id)
            
            if not api_key:
                logger.warning("Failed to activate plugin via CLI, setup may fail")
            
            # 6. Configure Nginx reverse proxy with path-based routing
            path_prefix = f"/{customer_id}"
            nginx_configured = self._configure_nginx(instance_ip, customer_id, port, path_prefix)
            
            if not nginx_configured:
                # Clean up container
                self._stop_container(instance_ip, customer_id)
                return {
                    'success': False,
                    'error_code': 'NGINX_CONFIG_FAILED',
                    'message': 'Failed to configure Nginx'
                }
            
            # 6. Schedule TTL cleanup
            expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
            self._schedule_cleanup(instance_ip, customer_id, path_prefix, ttl_minutes)
            
            # 7. Wait for health check
            # Use direct instance URL for WordPress setup (authentication)
            direct_url = f"http://{instance_ip}:{port}"
            alb_url = f"http://{self.alb_dns}{path_prefix}"
            
            if not self._wait_for_health(direct_url):
                logger.warning("Health check failed but returning URL anyway")
            
            logger.info(f"Target provisioned successfully: {alb_url}")
            
            return {
                'success': True,
                'target_url': direct_url,  # Direct URL for WordPress setup
                'public_url': alb_url,     # ALB URL for user access
                'wordpress_username': 'admin',
                'wordpress_password': wp_password,
                'api_key': api_key,        # Return the API key we extracted
                'expires_at': expires_at.isoformat() + 'Z',
                'status': 'running',
                'message': 'Target provisioned successfully',
                'instance_ip': instance_ip,  # For Apache reload after import
                'customer_id': customer_id   # Container name for Apache reload
            }
            
        except Exception as e:
            logger.error(f"Provisioning failed: {e}")
            return {
                'success': False,
                'error_code': 'PROVISION_ERROR',
                'message': f'Provisioning failed: {str(e)}'
            }
    
    def _find_least_loaded_instance(self) -> Optional[Dict]:
        """Find EC2 instance with least containers"""
        try:
            # Get instances from Auto Scaling Group
            response = self.asg_client.describe_auto_scaling_groups(
                AutoScalingGroupNames=[self.asg_name]
            )
            
            if not response['AutoScalingGroups']:
                logger.error(f"Auto Scaling Group {self.asg_name} not found")
                return None
            
            instances = response['AutoScalingGroups'][0]['Instances']
            running_instances = [i for i in instances if i['LifecycleState'] == 'InService']
            
            if not running_instances:
                logger.error("No running instances in ASG")
                return None
            
            # Get instance details
            instance_ids = [i['InstanceId'] for i in running_instances]
            ec2_response = self.ec2_client.describe_instances(InstanceIds=instance_ids)
            
            # For simplicity, return first available instance
            # In production, query container count via custom CloudWatch metric
            for reservation in ec2_response['Reservations']:
                for instance in reservation['Instances']:
                    if instance['State']['Name'] == 'running':
                        return instance
            
            return None
            
        except ClientError as e:
            logger.error(f"Failed to find instance: {e}")
            return None
    
    def _allocate_port(self, instance_ip: str) -> Optional[int]:
        """Allocate next available port on instance by checking running containers"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # Get list of ports already in use by Docker containers
            cmd = "docker ps --format '{{.Ports}}' | grep -oP '0.0.0.0:\\K[0-9]+' | sort -n"
            stdin, stdout, stderr = ssh.exec_command(cmd)
            used_ports_output = stdout.read().decode().strip()
            
            ssh.close()
            
            # Parse used ports
            used_ports = set()
            if used_ports_output:
                used_ports = set(int(p) for p in used_ports_output.split('\n') if p)
            
            logger.info(f"Ports in use on {instance_ip}: {used_ports}")
            
            # Find first available port in range
            for port in range(self.port_range_start, self.port_range_end + 1):
                if port not in used_ports:
                    logger.info(f"Allocated port {port}")
                    return port
            
            logger.error("All ports in range are in use")
            return None
            
        except Exception as e:
            logger.error(f"Failed to allocate port: {e}")
            # Fallback to first port if we can't check
            return self.port_range_start
    
    def _generate_password(self, length: int = 16) -> str:
        """Generate secure random password"""
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def _start_container(self, instance_ip: str, customer_id: str, port: int, wp_password: str) -> bool:
        """Start Docker container via SSH"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Connect to EC2 instance
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # Authenticate Docker with ECR
            logger.info("Authenticating with ECR...")
            ecr_login_cmd = "aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 044514005641.dkr.ecr.us-east-1.amazonaws.com"
            stdin, stdout, stderr = ssh.exec_command(ecr_login_cmd)
            ecr_status = stdout.channel.recv_exit_status()
            
            if ecr_status != 0:
                error = stderr.read().decode()
                logger.error(f"ECR login failed: {error}")
                ssh.close()
                return False
            
            logger.info("ECR authentication successful")
            
            # Start single WordPress+SQLite container
            # Use instance IP for WP_SITE_URL so authentication works
            docker_cmd = f"""
            docker run -d --pull always \
                --name {customer_id} \
                -p {port}:80 \
                -e WP_ADMIN_USER=admin \
                -e WP_ADMIN_PASSWORD={wp_password} \
                -e WP_ADMIN_EMAIL=admin@example.com \
                -e WP_SITE_URL=http://{instance_ip}:{port} \
                {self.docker_image}
            """
            
            stdin, stdout, stderr = ssh.exec_command(docker_cmd)
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                error = stderr.read().decode()
                logger.error(f"WordPress start failed: {error}")
                ssh.close()
                return False
            
            logger.info(f"WordPress container {customer_id} started on port {port}")
            
            # Wait for WordPress to auto-install (happens in background)
            logger.info("Waiting for WordPress to initialize (this takes ~30 seconds)...")
            time.sleep(35)
            
            ssh.close()
            
            logger.info(f"WordPress ready with admin user on port {port}")
            return True
                
        except Exception as e:
            logger.error(f"SSH command failed: {e}")
            return False
    
    def _configure_nginx(self, instance_ip: str, customer_id: str, port: int, path_prefix: str) -> bool:
        """Configure Nginx reverse proxy with path-based routing via SSH"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # Create Nginx config for path-based routing
            nginx_config = f"""
location {path_prefix}/ {{
    proxy_pass http://localhost:{port}/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix {path_prefix};
    
    # Rewrite redirects
    proxy_redirect / {path_prefix}/;
}}
"""
            
            # Write config to main nginx conf and reload
            commands = f"""
            echo '{nginx_config}' | sudo tee /etc/nginx/default.d/{customer_id}.conf
            sudo nginx -t && sudo systemctl reload nginx
            """
            
            stdin, stdout, stderr = ssh.exec_command(commands)
            exit_status = stdout.channel.recv_exit_status()
            
            ssh.close()
            
            if exit_status == 0:
                logger.info(f"Nginx configured for path {path_prefix}")
                return True
            else:
                error = stderr.read().decode()
                logger.error(f"Nginx config failed: {error}")
                return False
                
        except Exception as e:
            logger.error(f"Nginx configuration failed: {e}")
            return False
    
    def _schedule_cleanup(self, instance_ip: str, customer_id: str, path_prefix: str, ttl_minutes: int):
        """Schedule container cleanup via cron"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # Schedule one-time cleanup
            cleanup_script = f"""
            #!/bin/bash
            docker stop {customer_id}
            docker rm {customer_id}
            sudo rm -f /etc/nginx/default.d/{customer_id}.conf
            sudo systemctl reload nginx
            """
            
            commands = f"""
            echo '{cleanup_script}' > /tmp/cleanup_{customer_id}.sh
            chmod +x /tmp/cleanup_{customer_id}.sh
            echo "/tmp/cleanup_{customer_id}.sh" | at now + {ttl_minutes} minutes
            """
            
            stdin, stdout, stderr = ssh.exec_command(commands)
            stdout.channel.recv_exit_status()
            
            ssh.close()
            
            logger.info(f"Cleanup scheduled for {customer_id} in {ttl_minutes} minutes")
            
        except Exception as e:
            logger.warning(f"Failed to schedule cleanup: {e}")
    
    def _stop_container(self, instance_ip: str, customer_id: str):
        """Stop and remove container"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            ssh.exec_command(f"docker stop {customer_id} && docker rm {customer_id}")
            ssh.close()
            
        except Exception as e:
            logger.error(f"Failed to stop container: {e}")
    
    def reload_apache_in_container(self, instance_ip: str, customer_id: str):
        """Reload Apache inside container to reset database connections after import"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # Reload Apache to reset all database connections
            docker_cmd = f"sudo docker exec {customer_id} service apache2 reload"
            stdin, stdout, stderr = ssh.exec_command(docker_cmd)
            stdout.read()  # Wait for completion
            
            ssh.close()
            logger.info(f"Apache reloaded in container {customer_id}")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to reload Apache in container: {e}")
            return False
    
    def _wait_for_health(self, url: str, timeout: int = 30) -> bool:
        """Wait for WordPress to be healthy"""
        import requests
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, timeout=5, verify=False)
                if response.status_code in [200, 302]:
                    return True
            except Exception:
                pass
            time.sleep(2)
        
        return False

    def _activate_plugin_directly(self, instance_ip: str, customer_id: str) -> Optional[str]:
        """Activate plugin and get API key directly via docker exec (Bypasses Web UI)"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # PHP snippet to activate plugin and return API key
            # We use double quotes for the shell command so internal single quotes work
            php_code = '''
            require_once("/var/www/html/wp-load.php");
            include_once(ABSPATH . "wp-admin/includes/plugin.php");
            
            $plugin = "custom-migrator/custom-migrator.php";
            if (!is_plugin_active($plugin)) {
                activate_plugin($plugin);
            }
            
            // Ensure API key exists
            $api_key = get_option("custom_migrator_api_key");
            if (!$api_key) {
                $api_key = wp_generate_password(32, false);
                update_option("custom_migrator_api_key", $api_key);
            }
            
            // FORCE enable import - delete first then add fresh
            delete_option("custom_migrator_allow_import");
            add_option("custom_migrator_allow_import", true, "", "yes");
            
            // Flush all caches
            wp_cache_flush();
            if (function_exists("wp_cache_delete")) {
                wp_cache_delete("custom_migrator_allow_import", "options");
                wp_cache_delete("alloptions", "options");
            }
            
            // Verify it was set
            $verify = get_option("custom_migrator_allow_import");
            if (!$verify) {
                // Last resort: direct DB insert
                global $wpdb;
                $wpdb->replace(
                    $wpdb->options,
                    array("option_name" => "custom_migrator_allow_import", "option_value" => "1", "autoload" => "yes")
                );
            }
            
            echo $api_key;
            '''
            
            # Use base64 to avoid shell escaping issues with the PHP code
            import base64
            encoded_php = base64.b64encode(php_code.encode()).decode()
            docker_cmd = f"docker exec -u www-data {customer_id} php -r 'eval(base64_decode(\"{encoded_php}\"));'"
            
            logger.info(f"Executing direct activation on {customer_id} via base64 PHP...")
            stdin, stdout, stderr = ssh.exec_command(docker_cmd)
            api_key = stdout.read().decode().strip()
            error = stderr.read().decode().strip()
            
            ssh.close()
            
            if error and not api_key:
                logger.error(f"Direct activation failed: {error}")
                return None
                
            if api_key:
                logger.info(f"Direct activation successful, API key: {api_key[:10]}...")
                return api_key
            
            return None
                
        except Exception as e:
            logger.error(f"Direct activation exception: {e}")
            return None
