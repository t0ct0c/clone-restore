#!/bin/bash
set -e

echo "Waiting for WordPress files to be ready..."
while [ ! -f /var/www/html/wp-settings.php ]; do 
    sleep 1
done

echo "WordPress files ready, waiting for MySQL..."

# Wait for MySQL to be ready
echo "Waiting for MySQL connection..."
for i in {1..30}; do
    if mysqladmin ping -h "${WORDPRESS_DB_HOST}" -u "${WORDPRESS_DB_USER}" -p"${WORDPRESS_DB_PASSWORD}" --silent 2>/dev/null; then
        echo "MySQL is ready"
        break
    fi
    echo "Waiting for MySQL... ($i/30)"
    sleep 2
done

# Install custom migrator plugin
if [ ! -d /var/www/html/wp-content/plugins/custom-migrator ]; then
    echo "Installing custom migrator plugin..."
    cp -r /tmp/custom-migrator /var/www/html/wp-content/plugins/
fi

# Create necessary directories
mkdir -p /var/www/html/wp-content/uploads/custom-migrator/{tmp,exports,logs}

# Set permissions
chown -R www-data:www-data /var/www/html/wp-content
chmod -R 775 /var/www/html/wp-content/uploads

# Wait for WordPress to be accessible
echo "Waiting for WordPress to be accessible..."
sleep 5

# Check if WordPress is installed
if ! wp core is-installed --allow-root --path=/var/www/html 2>/dev/null; then
    echo "Installing WordPress..."
    
    # Get admin credentials from environment or use defaults
    WP_ADMIN_USER=${WP_ADMIN_USER:-admin}
    WP_ADMIN_PASSWORD=${WP_ADMIN_PASSWORD:-admin}
    WP_ADMIN_EMAIL=${WP_ADMIN_EMAIL:-admin@example.com}
    WP_SITE_URL=${WP_SITE_URL:-http://localhost}
    
    wp core install \
        --url="$WP_SITE_URL" \
        --title="WordPress Clone Target" \
        --admin_user="$WP_ADMIN_USER" \
        --admin_password="$WP_ADMIN_PASSWORD" \
        --admin_email="$WP_ADMIN_EMAIL" \
        --skip-email \
        --allow-root \
        --path=/var/www/html
    
    echo "WordPress installed successfully!"
    
    # Activate custom migrator plugin
    wp plugin activate custom-migrator --allow-root --path=/var/www/html || true
    
    # Configure plugin for import
    wp option update custom_migrator_allow_import "1" --allow-root --path=/var/www/html
    wp option update custom_migrator_api_key "migration-master-key" --allow-root --path=/var/www/html
    
    echo "Custom migrator plugin activated and configured with master key!"
else
    echo "WordPress already installed"
fi

# Fix .htaccess for REST API
cat > /var/www/html/.htaccess <<'EOF'
# BEGIN WordPress
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]
RewriteBase /
RewriteRule ^index\.php$ - [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule . /index.php [L]
</IfModule>
# END WordPress
EOF

chown www-data:www-data /var/www/html/.htaccess

echo "WordPress target ready!"
