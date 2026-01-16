#!/bin/bash
set -e

echo "Waiting for WordPress files to be ready..."
while [ ! -f /var/www/html/wp-settings.php ]; do 
    sleep 1
done

echo "WordPress files ready, configuring SQLite..."

# Install SQLite plugin
if [ ! -f /var/www/html/wp-content/db.php ]; then
    echo "Installing SQLite integration..."
    mkdir -p /var/www/html/wp-content/plugins
    cp -r /tmp/sqlite-database-integration /var/www/html/wp-content/plugins/
    cp /var/www/html/wp-content/plugins/sqlite-database-integration/db.copy /var/www/html/wp-content/db.php
fi

# Create wp-config.php for SQLite if it doesn't exist
if [ ! -f /var/www/html/wp-config.php ]; then
    echo "Creating wp-config.php for SQLite..."
    cat > /var/www/html/wp-config.php <<'WPCONFIG'
<?php
define( 'DB_NAME', 'wordpress' );
define( 'DB_USER', '' );
define( 'DB_PASSWORD', '' );
define( 'DB_HOST', '' );
define( 'DB_CHARSET', 'utf8' );
define( 'DB_COLLATE', '' );

define( 'AUTH_KEY',         'put your unique phrase here' );
define( 'SECURE_AUTH_KEY',  'put your unique phrase here' );
define( 'LOGGED_IN_KEY',    'put your unique phrase here' );
define( 'NONCE_KEY',        'put your unique phrase here' );
define( 'AUTH_SALT',        'put your unique phrase here' );
define( 'SECURE_AUTH_SALT', 'put your unique phrase here' );
define( 'LOGGED_IN_SALT',   'put your unique phrase here' );
define( 'NONCE_SALT',       'put your unique phrase here' );

$table_prefix = 'wp_';

define( 'WP_DEBUG', false );

if ( ! defined( 'ABSPATH' ) ) {
    define( 'ABSPATH', __DIR__ . '/' );
}

require_once ABSPATH . 'wp-settings.php';
WPCONFIG
    chown www-data:www-data /var/www/html/wp-config.php
fi

# Install custom migrator plugin
if [ ! -d /var/www/html/wp-content/plugins/custom-migrator ]; then
    echo "Installing custom migrator plugin..."
    cp -r /tmp/custom-migrator /var/www/html/wp-content/plugins/
fi

# Create necessary directories
mkdir -p /var/www/html/wp-content/uploads/custom-migrator/{tmp,exports,logs}
mkdir -p /var/www/html/wp-content/database

# Set permissions - MUST be writable for SQLite imports
chown -R www-data:www-data /var/www/html/wp-content
chmod -R 775 /var/www/html/wp-content/uploads
chmod -R 775 /var/www/html/wp-content/database

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
    
    echo "Custom migrator plugin activated!"
else
    echo "WordPress already installed"
fi

# Fix database file ownership AFTER WordPress install (wp core install runs as root)
# This is critical for SQLite imports to work
chown -R www-data:www-data /var/www/html/wp-content/database
chmod -R 775 /var/www/html/wp-content/database

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
