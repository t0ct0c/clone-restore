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





class EC2Provisioner:
    """Provision ephemeral WordPress targets on EC2 with Docker"""
    
    def __init__(self, region: str = 'us-east-1'):
        self.ec2_client = boto3.client('ec2', region_name=region)
        self.asg_client = boto3.client('autoscaling', region_name=region)
        self.cloudwatch_client = boto3.client('cloudwatch', region_name=region)
        self.elbv2_client = boto3.client('elbv2', region_name=region)
        self.region = region
        
        # Configuration (should be environment variables in production)
        self.asg_name = 'wp-targets-asg'
        self.docker_image = '044514005641.dkr.ecr.us-east-1.amazonaws.com/wordpress-target-sqlite:latest'
        self.alb_dns = 'clones.betaweb.ai'
        self.alb_listener_arn = 'arn:aws:elasticloadbalancing:us-east-1:044514005641:listener/app/wp-targets-alb/9deaa3f04bc5506b/f6542ccc3f16bfd7'
        self.target_group_arn = 'arn:aws:elasticloadbalancing:us-east-1:044514005641:targetgroup/wp-targets-tg/08695f0f6e7e5fbf'
        self.management_ip = '10.0.4.2' # Private IP of the management host running Loki/Tempo
        self.ssh_key_path = '/app/ssh/wp-targets-key.pem'
        self.port_range_start = 8001
        self.port_range_end = 8050
        
        # MySQL root password from environment (set by Terraform output)
        import os
        self.mysql_root_password = os.getenv('MYSQL_ROOT_PASSWORD', 'default_insecure_password')
    
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
            
            # 7.5. Create ALB listener rule for path-based routing to this instance
            instance_id = self._get_instance_id(instance_ip)
            if instance_id:
                alb_rule_created = self._create_alb_listener_rule(customer_id, path_prefix, instance_id)
                if not alb_rule_created:
                    logger.warning(f"Failed to create ALB listener rule for {path_prefix}, clone may not be accessible via ALB")
            else:
                logger.warning(f"Could not determine instance ID for {instance_ip}, skipping ALB rule creation")
            
            # 8. Schedule TTL cleanup
            expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
            self._schedule_cleanup(instance_ip, customer_id, path_prefix, ttl_minutes, db_password)
            
            # 9. Wait for health check
            # Use direct instance URL for WordPress setup (authentication)
            direct_url = f"http://{instance_ip}:{port}"
            alb_url = f"https://{self.alb_dns}{path_prefix}"
            
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
        """Find EC2 instance with least containers and scale up if needed"""
        try:
            # Get instances from Auto Scaling Group
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
                    logger.info("Triggered scale up from zero")
                return None
            
            # Get instance details to get IPs
            instance_ids = [i['InstanceId'] for i in running_instances]
            ec2_response = self.ec2_client.describe_instances(InstanceIds=instance_ids)
            
            candidates = []
            for reservation in ec2_response['Reservations']:
                for instance in reservation['Instances']:
                    if instance['State']['Name'] == 'running':
                        # Count containers on this instance
                        load = self._get_instance_load(instance.get('PrivateIpAddress'))
                        candidates.append({
                            'instance': instance,
                            'load': load
                        })
            
            if not candidates:
                return None
            
            # Sort by load (least containers first)
            candidates.sort(key=lambda x: x['load'])
            best_candidate = candidates[0]
            
            # If even the least loaded instance is near capacity, trigger scale up
            max_containers = self.port_range_end - self.port_range_start + 1
            if best_candidate['load'] >= (max_containers * 0.8):
                current_desired = asg['DesiredCapacity']
                if current_desired < asg['MaxSize']:
                    logger.info(f"Instances near capacity ({best_candidate['load']}/{max_containers}). Scaling up ASG.")
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
            
            # Count running containers (excluding infrastructure ones like 'mysql' or 'loki' if present)
            # We assume our clone containers have a specific naming pattern or we just count all
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
            return 999  # Treat as full if unreachable
    
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
    
    def _create_mysql_database(self, instance_ip: str, customer_id: str, db_password: str, mysql_root_password: str) -> bool:
        """Create MySQL database and user for WordPress instance"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # Sanitize customer_id for database name (replace hyphens with underscores)
            db_name = f"wp_{customer_id.replace('-', '_')}"
            db_user = db_name
            
            # Create database and user via MySQL CLI
            mysql_commands = (
                f"CREATE DATABASE IF NOT EXISTS {db_name}; "
                f"CREATE USER IF NOT EXISTS '{db_user}'@'%' IDENTIFIED BY '{db_password}'; "
                f"GRANT ALL PRIVILEGES ON {db_name}.* TO '{db_user}'@'%'; "
                "FLUSH PRIVILEGES;"
            )
            
            # Execute MySQL commands (escape password for shell)
            import shlex
            docker_cmd = f"docker exec mysql mysql -uroot -p{shlex.quote(mysql_root_password)} -e {shlex.quote(mysql_commands)}"
            
            stdin, stdout, stderr = ssh.exec_command(docker_cmd)
            exit_status = stdout.channel.recv_exit_status()
            
            ssh.close()
            
            if exit_status == 0:
                logger.info(f"MySQL database {db_name} created successfully")
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
            
            # Sanitize customer_id for database name
            db_name = f"wp_{customer_id.replace('-', '_')}"
            db_user = db_name
            
            # Start WordPress container with MySQL configuration and Loki logging
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
                -e WORDPRESS_CONFIG_EXTRA="define('MYSQL_CLIENT_FLAGS', MYSQLI_CLIENT_SSL_DONT_VERIFY_SERVER_CERT);" \
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
            
            # Wait for WordPress and Migrator Plugin to be ready via status endpoint
            logger.info("Waiting for WordPress and Migrator Plugin to initialize...")
            ready = False
            for i in range(20):  # 100 seconds total
                try:
                    # Check status via API to ensure plugin is loaded and active
                    # Use http because it's internal VPC traffic
                    resp = requests.get(
                        f"http://{instance_ip}:{port}/wp-json/custom-migrator/v1/status",
                        headers={'X-Migrator-Key': 'migration-master-key'},
                        timeout=5
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get('import_allowed'):
                            logger.info(f"WordPress and Migrator Plugin ready on port {port}")
                            ready = True
                            break
                except Exception:
                    pass
                time.sleep(5)
            
            if not ready:
                logger.warning(f"WordPress might not be fully ready on port {port}, proceeding anyway...")
            
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
    # Pass through the real host so WordPress generates correct URLs
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix {path_prefix};

    # Rewrite redirects back through the path prefix
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
    
    def _schedule_cleanup(self, instance_ip: str, customer_id: str, path_prefix: str, ttl_minutes: int, db_password: str):
        """Schedule container and database cleanup via cron"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # Sanitize customer_id for database name
            db_name = f"wp_{customer_id.replace('-', '_')}"

            # Schedule one-time cleanup including database drop
            # Escape MySQL password for shell using single quotes
            escaped_password = self.mysql_root_password.replace("'", "'\\''")
            cleanup_script = f"""
            #!/bin/bash
            # Stop and remove container
            docker stop {customer_id}
            docker rm {customer_id}

            # Drop MySQL database and user
            docker exec mysql mysql -uroot -p'{escaped_password}' -e "DROP DATABASE IF EXISTS {db_name}; DROP USER IF EXISTS '{db_name}'@'%';"

            # Remove Nginx config
            sudo rm -f /etc/nginx/default.d/{customer_id}.conf
            sudo systemctl reload nginx

            # Delete ALB listener rule and target group
            LISTENER_ARN="{self.alb_listener_arn}"
            REGION="us-east-1"

            # Find and delete the ALB listener rule for this clone
            RULE_ARN=$(aws elbv2 describe-rules --region $REGION --listener-arn "$LISTENER_ARN" --output json | python3 -c "
import json, sys
rules = json.load(sys.stdin)['Rules']
for rule in rules:
    for cond in rule.get('Conditions', []):
        for val in cond.get('Values', []):
            if '{path_prefix}' in val:
                print(rule['RuleArn'])
                break
" 2>/dev/null)

            if [ -n "$RULE_ARN" ]; then
                # Get target group ARN before deleting rule
                TG_ARN=$(aws elbv2 describe-rules --region $REGION --rule-arns "$RULE_ARN" --output json | python3 -c "
import json, sys
try:
    rule = json.load(sys.stdin)['Rules'][0]
    for action in rule.get('Actions', []):
        if action.get('Type') == 'forward':
            print(action.get('TargetGroupArn', ''))
except: pass
" 2>/dev/null)

                # Delete ALB listener rule
                aws elbv2 delete-rule --region $REGION --rule-arn "$RULE_ARN" 2>/dev/null

                # Delete target group if it exists
                if [ -n "$TG_ARN" ]; then
                    aws elbv2 delete-target-group --region $REGION --target-group-arn "$TG_ARN" 2>/dev/null
                fi
            fi
            """
            
            commands = f"""
            echo '{cleanup_script}' > /tmp/cleanup_{customer_id}.sh
            chmod +x /tmp/cleanup_{customer_id}.sh
            echo "/tmp/cleanup_{customer_id}.sh" | at now + {ttl_minutes} minutes
            """
            
            stdin, stdout, stderr = ssh.exec_command(commands)
            stdout.channel.recv_exit_status()
            
            ssh.close()
            
            logger.info(f"Cleanup scheduled for {customer_id} in {ttl_minutes} minutes (includes database drop)")
            
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
    
    def activate_plugin_in_container(self, instance_ip: str, customer_id: str, plugin_slug: str = "custom-migrator") -> bool:
        """Activate a plugin inside a WordPress container via WP-CLI.
        
        The clone import process deactivates plugins, so this must be called
        after import to re-enable the migrator plugin on the clone.
        """
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            docker_cmd = f"sudo docker exec {customer_id} wp plugin activate {plugin_slug} --path=/var/www/html --allow-root"
            stdin, stdout, stderr = ssh.exec_command(docker_cmd)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode().strip()
            
            ssh.close()
            
            if exit_status == 0:
                logger.info(f"Plugin '{plugin_slug}' activated in container {customer_id}: {output}")
                return True
            else:
                error = stderr.read().decode().strip()
                logger.error(f"Plugin activation failed in {customer_id}: {error}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to activate plugin in container {customer_id}: {e}")
            return False
    
    def run_wp_cli_in_container(self, instance_ip: str, customer_id: str, wp_cli_command: str) -> bool:
        """Run an arbitrary WP-CLI command inside a WordPress container via SSH."""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            docker_cmd = f"sudo docker exec {customer_id} wp {wp_cli_command} --path=/var/www/html --allow-root"
            stdin, stdout, stderr = ssh.exec_command(docker_cmd)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode().strip()
            
            ssh.close()
            
            if exit_status == 0:
                logger.info(f"WP-CLI '{wp_cli_command}' in {customer_id}: {output}")
                return True
            else:
                error = stderr.read().decode().strip()
                logger.error(f"WP-CLI '{wp_cli_command}' failed in {customer_id}: {error}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to run WP-CLI in {customer_id}: {e}")
            return False
    
    def update_wordpress_urls(self, instance_ip: str, customer_id: str, public_url: str) -> bool:
        """Force-lock WordPress home/siteurl to prevent auto-correction via wp-config.php constants"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # Step 1: Update database URLs
            docker_cmd = f"""
            sudo docker exec {customer_id} wp db query \
                'UPDATE wp_options SET option_value = \"{public_url}\" WHERE option_name IN (\"home\", \"siteurl\");' \
                --path=/var/www/html --allow-root
            """
            stdin, stdout, stderr = ssh.exec_command(docker_cmd)
            stdout.channel.recv_exit_status()
            
            # Step 2: Lock URLs in wp-config.php as constants so WordPress can't auto-change them
            # This prevents WordPress from detecting Host header mismatches and "correcting" the URLs
            wp_config_cmd = f"""
            sudo docker exec {customer_id} bash -c '
            # Find the line before wp-settings.php require
            line_num=$(grep -n "require_once ABSPATH . \'wp-settings.php\';" /var/www/html/wp-config.php | cut -d: -f1)
            if [ ! -z "$line_num" ]; then
                # Insert static URL definitions before wp-settings.php
                sed -i "$((line_num-1))i /* Lock site URLs to prevent auto-correction */\\
define(\\"WP_HOME\\", \\"{public_url}\\");\\
define(\\"WP_SITEURL\\", \\"{public_url}\\");" /var/www/html/wp-config.php
            fi
            # Comment out dynamic URL detection that overrides static definitions
            sed -i "/^define.*WP_HOME.*\\$proto/s/^/\\/\\/ /" /var/www/html/wp-config.php
            sed -i "/^define.*WP_SITEURL.*\\$proto/s/^/\\/\\/ /" /var/www/html/wp-config.php
            sed -i "/^define.*COOKIEPATH.*\\$prefix/s/^/\\/\\/ /" /var/www/html/wp-config.php
            '
            """
            stdin, stdout, stderr = ssh.exec_command(wp_config_cmd)
            exit_status = stdout.channel.recv_exit_status()
            
            ssh.close()
            
            if exit_status == 0:
                logger.info(f"WordPress URLs locked to {public_url} in wp-config.php")
                return True
            else:
                logger.warning(f"Failed to lock WordPress URLs (exit {exit_status})")
                return False
            
        except Exception as e:
            logger.warning(f"Failed to lock WordPress URLs: {e}")
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
        """Activate plugin and set a fixed API key for the migration phase"""
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            ssh.connect(
                instance_ip,
                username='ec2-user',
                key_filename=self.ssh_key_path,
                timeout=30
            )
            
            # Use a fixed key for the migration setup phase to avoid race conditions
            fixed_key = "migration-master-key"
            
            # Retry a few times if the container is still installing
            for attempt in range(3):
                commands = f"""
                docker exec -u www-data {customer_id} wp plugin activate custom-migrator --path=/var/www/html
                docker exec -u www-data {customer_id} wp option update custom_migrator_allow_import 1 --path=/var/www/html
                docker exec -u www-data {customer_id} wp option update custom_migrator_api_key {fixed_key} --path=/var/www/html
                """
                
                stdin, stdout, stderr = ssh.exec_command(commands)
                exit_status = stdout.channel.recv_exit_status()
                
                if exit_status == 0:
                    logger.info(f"Direct activation successful with fixed migration key")
                    ssh.close()
                    return fixed_key
                
                logger.warning(f"Activation attempt {attempt + 1} failed, retrying...")
                time.sleep(5)
            
            ssh.close()
            return None
                
        except Exception as e:
            logger.error(f"Direct activation exception: {e}")
            return None
    
    def _get_instance_id(self, instance_ip: str) -> Optional[str]:
        """Get EC2 instance ID from private IP address"""
        try:
            response = self.ec2_client.describe_instances(
                Filters=[
                    {'Name': 'private-ip-address', 'Values': [instance_ip]},
                    {'Name': 'instance-state-name', 'Values': ['running']}
                ]
            )
            
            if response['Reservations'] and response['Reservations'][0]['Instances']:
                instance_id = response['Reservations'][0]['Instances'][0]['InstanceId']
                logger.info(f"Found instance ID {instance_id} for IP {instance_ip}")
                return instance_id
            
            logger.warning(f"No running instance found with IP {instance_ip}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to get instance ID for {instance_ip}: {e}")
            return None
    
    def _create_alb_listener_rule(self, customer_id: str, path_prefix: str, instance_id: str) -> bool:
        """Create ALB listener rule to route path to specific instance"""
        try:
            # Get current rules to determine priority
            response = self.elbv2_client.describe_rules(ListenerArn=self.alb_listener_arn)
            existing_priorities = [int(rule['Priority']) for rule in response['Rules'] if rule['Priority'] != 'default']
            next_priority = max(existing_priorities) + 1 if existing_priorities else 1
            
            logger.info(f"Creating ALB rule with priority {next_priority} for {path_prefix} -> {instance_id}")
            
            # Create target group for this specific instance
            target_group_name = f"clone-{customer_id}"[:32]  # ALB target group names max 32 chars
            
            # Check if target group already exists
            try:
                tg_response = self.elbv2_client.describe_target_groups(Names=[target_group_name])
                target_group_arn = tg_response['TargetGroups'][0]['TargetGroupArn']
                logger.info(f"Using existing target group: {target_group_arn}")
            except:
                # Create new target group
                tg_response = self.elbv2_client.create_target_group(
                    Name=target_group_name,
                    Protocol='HTTP',
                    Port=80,
                    VpcId=self._get_vpc_id(),
                    HealthCheckPath='/',
                    HealthCheckIntervalSeconds=30,
                    HealthCheckTimeoutSeconds=5,
                    HealthyThresholdCount=2,
                    UnhealthyThresholdCount=2,
                    Matcher={'HttpCode': '200,302'}
                )
                target_group_arn = tg_response['TargetGroups'][0]['TargetGroupArn']
                logger.info(f"Created target group: {target_group_arn}")
                
                # Register instance with target group
                self.elbv2_client.register_targets(
                    TargetGroupArn=target_group_arn,
                    Targets=[{'Id': instance_id, 'Port': 80}]
                )
                logger.info(f"Registered instance {instance_id} with target group")
            
            # Create listener rule for path-based routing
            self.elbv2_client.create_rule(
                ListenerArn=self.alb_listener_arn,
                Priority=next_priority,
                Conditions=[
                    {
                        'Field': 'path-pattern',
                        'Values': [f"{path_prefix}/*"]
                    }
                ],
                Actions=[
                    {
                        'Type': 'forward',
                        'TargetGroupArn': target_group_arn
                    }
                ]
            )
            
            logger.info(f"Successfully created ALB rule for {path_prefix} -> {instance_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create ALB listener rule: {e}")
            return False
    
    def _get_vpc_id(self) -> str:
        """Get VPC ID from target group"""
        try:
            response = self.elbv2_client.describe_target_groups(
                TargetGroupArns=[self.target_group_arn]
            )
            return response['TargetGroups'][0]['VpcId']
        except Exception as e:
            logger.error(f"Failed to get VPC ID: {e}")
            # Fallback to hardcoded VPC ID from Terraform
            return 'vpc-03ba82902d6825692'
