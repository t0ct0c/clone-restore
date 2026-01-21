"""
AWS EC2 Provisioning Module

Handles ephemeral WordPress target provisioning on EC2 Auto Scaling with Docker.
"""

from loguru import logger
import time
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, Dict
import boto3
import paramiko
from botocore.exceptions import ClientError
import requests
import shlex


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
        self.management_ip = '10.0.4.2' # Private IP of the management host running Loki/Tempo
        self.ssh_key_path = '/app/ssh/wp-targets-key.pem'
        self.port_range_start = 8001
        self.port_range_end = 8050
        
        # MySQL root password from environment (set by Terraform output)
        import os
        self.mysql_root_password = os.getenv('MYSQL_ROOT_PASSWORD', 'default_insecure_password')
        
        # FIX: Remove accidental backslashes that some shell environments add before exclamation marks
        if "\\!" in self.mysql_root_password:
            logger.info("Sanitizing MySQL root password (removing accidental backslashes)")
            self.mysql_root_password = self.mysql_root_password.replace("\\!", "!")
    
    def provision_target(self, customer_id: str, ttl_minutes: int = 30) -> Dict:
        """
        Provision ephemeral WordPress target
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
            
            # 3. Generate WordPress and database credentials
            wp_password = self._generate_password()
            db_password = self._generate_password()
            
            # 4. Create MySQL database for this WordPress instance
            db_created = self._create_mysql_database(
                instance_ip,
                customer_id,
                db_password,
                self.mysql_root_password
            )
            
            if not db_created:
                return {
                    'success': False,
                    'error_code': 'DB_CREATE_FAILED',
                    'message': 'Failed to create MySQL database'
                }
            
            # 5. Start Docker container via SSH
            container_started = self._start_container(
                instance_ip,
                customer_id,
                port,
                wp_password,
                db_password
            )
            
            if not container_started:
                return {
                    'success': False,
                    'error_code': 'CONTAINER_START_FAILED',
                    'message': 'Failed to start Docker container'
                }
            
            # 6. Activate plugin and get API key directly (Bypass Browser)
            logger.info(f"Activating plugin directly in container {customer_id}...")
            api_key = self._activate_plugin_directly(instance_ip, customer_id)
            
            if not api_key:
                logger.warning("Failed to activate plugin via CLI, setup may fail")
            
            # 7. Configure Nginx reverse proxy with path-based routing
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
            
            # 8. Reload Apache in the container to ensure it picks up any config changes and resets connections
            logger.info("Reloading Apache in container to ensure clean state...")
            self.reload_apache_in_container(instance_ip, customer_id)
            
            # 9. Schedule TTL cleanup
            expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
            self._schedule_cleanup(instance_ip, customer_id, path_prefix, ttl_minutes, db_password)
            
            # 9. Wait for health check
            direct_url = f"http://{instance_ip}:{port}"
            alb_url = f"http://{self.alb_dns}{path_prefix}"
            
            if not self._wait_for_health(direct_url):
                logger.warning("Health check failed but returning URL anyway")
            
            logger.info(f"Target provisioned successfully: {alb_url}")
            
            return {
                'success': True,
                'target_url': direct_url,
                'public_url': alb_url,
                'wordpress_username': 'admin',
                'wordpress_password': wp_password,
                'api_key': api_key,
                'expires_at': expires_at.isoformat() + 'Z',
                'status': 'running',
                'message': 'Target provisioned successfully',
                'instance_ip': instance_ip,
                'customer_id': customer_id
            }
            
        except Exception as e:
            logger.error(f"Provisioning failed: {e}")
            return {
                'success': False,
                'error_code': 'PROVISION_ERROR',
                'message': f'Provisioning failed: {str(e)}'
            }
    
    def _find_least_loaded_instance(self) -> Optional[Dict]:
        """Find EC2 instance with least containers and scale up if needed"""
        try:
            response = self.asg_client.describe_auto_scaling_groups(
                AutoScalingGroupNames=[self.asg_name]
            )
            
            if not response['AutoScalingGroups']:
                logger.error(f"Auto Scaling Group {self.asg_name} not found")
                return None
            
            asg = response['AutoScalingGroups'][0]
            instances = asg['Instances']
            running_instances = [i for i in instances if i['LifecycleState'] == 'InService']
            
            if not running_instances:
                logger.warning("No running instances in ASG, checking if we can scale from zero")
                if asg['DesiredCapacity'] == 0:
                    self.asg_client.update_auto_scaling_group(
                        AutoScalingGroupName=self.asg_name,
                        DesiredCapacity=1
                    )
                return None
            
            instance_ids = [i['InstanceId'] for i in running_instances]
            ec2_response = self.ec2_client.describe_instances(InstanceIds=instance_ids)
            
            candidates = []
            for reservation in ec2_response['Reservations']:
                for instance in reservation['Instances']:
                    if instance['State']['Name'] == 'running':
                        load = self._get_instance_load(instance.get('PrivateIpAddress'))
                        candidates.append({
                            'instance': instance,
                            'load': load
                        })
            
            if not candidates:
                return None
            
            candidates.sort(key=lambda x: x['load'])
            best_candidate = candidates[0]
            
            max_containers = self.port_range_end - self.port_range_start + 1
            if best_candidate['load'] >= (max_containers * 0.8):
                current_desired = asg['DesiredCapacity']
                if current_desired < asg['MaxSize']:
                    self.asg_client.update_auto_scaling_group(
                        AutoScalingGroupName=self.asg_name,
                        DesiredCapacity=current_desired + 1
                    )
            
            return best_candidate['instance']
            
        except Exception as e:
            logger.error(f"Failed to find instance: {e}")
            return None

    def _get_instance_load(self, instance_ip: str) -> int:
        """Count running containers on an instance via SSH"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(instance_ip, username='ec2-user', key_filename=self.ssh_key_path, timeout=10)
            
            cmd = "docker ps -q | wc -l"
            stdin, stdout, stderr = ssh.exec_command(cmd)
            count = int(stdout.read().decode().strip() or 0)
            
            # Proactive disk cleanup
            df_cmd = "df --output=pcent / | tail -1 | tr -dc '0-9'"
            stdin, stdout, stderr = ssh.exec_command(df_cmd)
            usage = int(stdout.read().decode().strip() or 0)
            if usage > 80:
                logger.info(f"Disk usage on {instance_ip} is {usage}%. Running docker system prune.")
                ssh.exec_command("docker system prune -f")
            
            ssh.close()
            return count
        except Exception as e:
            logger.warning(f"Could not get load for {instance_ip}: {e}")
            return 999
    
    def _allocate_port(self, instance_ip: str) -> Optional[int]:
        """Allocate next available port on instance by checking running containers"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(instance_ip, username='ec2-user', key_filename=self.ssh_key_path, timeout=30)
            
            cmd = "docker ps --format '{{.Ports}}' | grep -oP '0.0.0.0:\\K[0-9]+' | sort -n"
            stdin, stdout, stderr = ssh.exec_command(cmd)
            used_ports_output = stdout.read().decode().strip()
            
            ssh.close()
            
            used_ports = set()
            if used_ports_output:
                used_ports = set(int(p) for p in used_ports_output.split('\n') if p)
            
            for port in range(self.port_range_start, self.port_range_end + 1):
                if port not in used_ports:
                    return port
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to allocate port: {e}")
            return self.port_range_start
    
    def _generate_password(self, length: int = 16) -> str:
        """Generate secure random password"""
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def _create_mysql_database(self, instance_ip: str, customer_id: str, db_password: str, mysql_root_password: str) -> bool:
        """Create MySQL database and user for WordPress instance"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(instance_ip, username='ec2-user', key_filename=self.ssh_key_path, timeout=30)
            
            db_name = f"wp_{customer_id.replace('-', '_')}"
            db_user = db_name
            
            mysql_commands = (
                f"CREATE DATABASE IF NOT EXISTS {db_name}; "
                f"CREATE USER IF NOT EXISTS '{db_user}'@'%' IDENTIFIED BY '{db_password}'; "
                f"GRANT ALL PRIVILEGES ON {db_name}.* TO '{db_user}'@'%'; "
                "FLUSH PRIVILEGES;"
            )
            
            docker_cmd = f"docker exec -e MYSQL_PWD={shlex.quote(mysql_root_password)} mysql mysql -uroot -e {shlex.quote(mysql_commands)}"
            
            stdin, stdout, stderr = ssh.exec_command(docker_cmd)
            exit_status = stdout.channel.recv_exit_status()
            
            ssh.close()
            
            if exit_status == 0:
                return True
            else:
                error = stderr.read().decode()
                logger.error(f"MySQL database creation failed: {error}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to create MySQL database: {e}")
            return False
    
    def _start_container(self, instance_ip: str, customer_id: str, port: int, wp_password: str, db_password: str) -> bool:
        """Start Docker container via SSH"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(instance_ip, username='ec2-user', key_filename=self.ssh_key_path, timeout=30)
            
            ecr_login_cmd = "aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 044514005641.dkr.ecr.us-east-1.amazonaws.com"
            ssh.exec_command(ecr_login_cmd)
            
            db_name = f"wp_{customer_id.replace('-', '_')}"
            db_user = db_name
            
            docker_cmd = f"""
            docker run -d --pull always \
                --name {customer_id} \
                -p {port}:80 \
                --add-host=host.docker.internal:host-gateway \
                --log-driver loki \
                --log-opt loki-url="http://{self.management_ip}:3100/loki/api/v1/push" \
                --log-opt loki-external-labels="job=wp-migration,container_name={customer_id}" \
                -e WORDPRESS_DB_HOST=host.docker.internal:3306 \
                -e WORDPRESS_DB_NAME={db_name} \
                -e WORDPRESS_DB_USER={db_user} \
                -e WORDPRESS_DB_PASSWORD={db_password} \
                -e WP_ADMIN_USER=admin \
                -e WP_ADMIN_PASSWORD={wp_password} \
                -e WP_ADMIN_EMAIL=admin@example.com \
                -e WP_SITE_URL=http://{instance_ip}:{port} \
                -e WP_SUBPATH=/{customer_id} \
                -e WORDPRESS_CONFIG_EXTRA="define('MYSQL_CLIENT_FLAGS', MYSQLI_CLIENT_SSL_DONT_VERIFY_SERVER_CERT);" \
                {self.docker_image}
            """
            
            stdin, stdout, stderr = ssh.exec_command(docker_cmd)
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                ssh.close()
                return False
            
            # Wait for WordPress and Migrator Plugin
            ready = False
            for i in range(20):
                try:
                    resp = requests.get(
                        f"http://{instance_ip}:{port}/wp-json/custom-migrator/v1/status",
                        headers={'X-Migrator-Key': 'migration-master-key'},
                        timeout=5
                    )
                    if resp.status_code == 200 and resp.json().get('import_allowed'):
                        ready = True
                        break
                except Exception:
                    pass
                time.sleep(5)
            
            ssh.close()
            return True
                
        except Exception as e:
            logger.error(f"SSH command failed: {e}")
            return False
    
    def _configure_nginx(self, instance_ip: str, customer_id: str, port: int, path_prefix: str) -> bool:
        """Configure Nginx reverse proxy with path-based routing via SSH"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(instance_ip, username='ec2-user', key_filename=self.ssh_key_path, timeout=30)
            
            # Create Nginx config for path-based routing
            # This version preserves the prefix so the backend can handle it correctly
            nginx_config = f"""
location {path_prefix} {{
    proxy_pass http://localhost:{port};
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    
    # Handle protocol forwarding
    set $fixed_proto $scheme;
    if ($http_x_forwarded_proto != "") {{
        set $fixed_proto $http_x_forwarded_proto;
    }}
    proxy_set_header X-Forwarded-Proto $fixed_proto;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix {path_prefix};
    
    # Use HTTP 1.1 for better connection handling
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    
    # Disable compression from backend
    proxy_set_header Accept-Encoding "";
    gzip off;
    
    # Buffers for WordPress admin
    proxy_buffer_size 128k;
    proxy_buffers 4 256k;
    proxy_busy_buffers_size 256k;
    
    # Increase timeouts for large imports
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    
    # Buffering on is usually safer for header processing
    proxy_buffering on;
}}
"""
            
            commands = f"""
sudo tee /etc/nginx/default.d/{customer_id}.conf << 'EOF'
{nginx_config}
EOF
sudo nginx -t && sudo systemctl reload nginx
"""
            
            stdin, stdout, stderr = ssh.exec_command(commands)
            exit_status = stdout.channel.recv_exit_status()
            ssh.close()
            
            if exit_status == 0:
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"Nginx configuration exception: {e}")
            return False
    
    def _schedule_cleanup(self, instance_ip: str, customer_id: str, path_prefix: str, ttl_minutes: int, db_password: str):
        """Schedule container and database cleanup via cron"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(instance_ip, username='ec2-user', key_filename=self.ssh_key_path, timeout=30)
            
            db_name = f"wp_{customer_id.replace('-', '_')}"
            escaped_password = self.mysql_root_password.replace("'", "'\\''")
            cleanup_script = f"""
            #!/bin/bash
            docker stop {customer_id}
            docker rm {customer_id}
            docker exec -e MYSQL_PWD='{escaped_password}' mysql mysql -uroot -e "DROP DATABASE IF EXISTS {db_name}; DROP USER IF EXISTS '{db_name}'@'%';"
            sudo rm -f /etc/nginx/default.d/{customer_id}.conf
            sudo systemctl reload nginx
            """
            
            commands = f"""
            echo '{cleanup_script}' > /tmp/cleanup_{customer_id}.sh
            chmod +x /tmp/cleanup_{customer_id}.sh
            echo "/tmp/cleanup_{customer_id}.sh" | at now + {ttl_minutes} minutes
            """
            ssh.exec_command(commands)
            ssh.close()
        except Exception:
            pass
    
    def _stop_container(self, instance_ip: str, customer_id: str):
        """Stop and remove container"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(instance_ip, username='ec2-user', key_filename=self.ssh_key_path, timeout=30)
            ssh.exec_command(f"docker stop {customer_id} && docker rm {customer_id}")
            ssh.close()
        except Exception:
            pass
    
    def reload_apache_in_container(self, instance_ip: str, customer_id: str):
        """Reload Apache inside container to reset database connections after import"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(instance_ip, username='ec2-user', key_filename=self.ssh_key_path, timeout=30)
            docker_cmd = f"sudo docker exec {customer_id} service apache2 reload"
            ssh.exec_command(docker_cmd)
            ssh.close()
            return True
        except Exception:
            return False
    
    def _wait_for_health(self, url: str, timeout: int = 30) -> bool:
        """Wait for WordPress to be healthy"""
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
        """Activate plugin and set a fixed API key for the migration phase"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(instance_ip, username='ec2-user', key_filename=self.ssh_key_path, timeout=30)
            fixed_key = "migration-master-key"
            for attempt in range(3):
                commands = f"""
                docker exec -u www-data {customer_id} wp plugin activate custom-migrator --path=/var/www/html
                docker exec -u www-data {customer_id} wp option update custom_migrator_allow_import 1 --path=/var/www/html
                docker exec -u www-data {customer_id} wp option update custom_migrator_api_key {fixed_key} --path=/var/www/html
                """
                stdin, stdout, stderr = ssh.exec_command(commands)
                if stdout.channel.recv_exit_status() == 0:
                    ssh.close()
                    return fixed_key
                time.sleep(5)
            ssh.close()
            return None
        except Exception:
            return None
