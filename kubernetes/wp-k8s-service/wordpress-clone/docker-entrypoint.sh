#!/bin/bash
set -e

# Wait for MySQL sidecar to be ready
echo "Waiting for MySQL sidecar..."
while ! mysqladmin ping -h"127.0.0.1" --silent; do
    sleep 1
done
echo "MySQL is ready"

# Copy WordPress files if not already present
if [[ ! -f /var/www/html/wp-includes/version.php ]]; then
    echo "Copying WordPress files..."
    cp -a /usr/src/wordpress/. /var/www/html/
    chown -R www-data:www-data /var/www/html/
fi

WORDPRESS_DB_HOST="${WORDPRESS_DB_HOST:-127.0.0.1:3306}"
WORDPRESS_DB_NAME="${WORDPRESS_DB_NAME:-wordpress}"
WORDPRESS_DB_USER="${WORDPRESS_DB_USER:-wordpress}"
WORDPRESS_DB_PASSWORD="${WORDPRESS_DB_PASSWORD}"

# ------------------------------------------------------------------
# ALWAYS ensure wp-config.php exists.
#
# The import plugin may modify wp-config.php (changing table prefix,
# WP_HOME, WP_SITEURL).  If the container is restarted (liveness
# probe, OOM, etc.) the writable layer without an emptyDir volume
# would be lost and we'd land on the setup-config wizard.  With an
# emptyDir volume the file survives restarts but we still guard
# against its absence here.
# ------------------------------------------------------------------
if [[ ! -f /var/www/html/wp-config.php ]]; then
    echo "Creating wp-config.php..."
    SITE_URL="http://localhost"
    cat > /var/www/html/wp-config.php << EOFCONFIG
<?php
define('DB_NAME', '$WORDPRESS_DB_NAME');
define('DB_USER', '$WORDPRESS_DB_USER');
define('DB_PASSWORD', '$WORDPRESS_DB_PASSWORD');
define('DB_HOST', '$WORDPRESS_DB_HOST');
define('DB_CHARSET', 'utf8');
define('DB_COLLATE', '');
\$table_prefix = 'wp_';
define('WP_DEBUG', false);
define('WP_SITEURL', '$SITE_URL');
define('WP_HOME', '$SITE_URL');

if ( ! defined( 'ABSPATH' ) ) {
    define( 'ABSPATH', __DIR__ . '/' );
}
require_once ABSPATH . 'wp-settings.php';
EOFCONFIG
    chown www-data:www-data /var/www/html/wp-config.php
else
    echo "wp-config.php already exists, keeping it"
fi

# ------------------------------------------------------------------
# Install WordPress tables via WP-CLI if not already present.
# This replaces the old raw-SQL approach that created tables with
# wrong schemas (e.g. CREATE TABLE wp_comments LIKE wp_posts).
# ------------------------------------------------------------------
DB_HOST_ONLY=$(echo "$WORDPRESS_DB_HOST" | cut -d: -f1)
DB_PORT_ONLY=$(echo "$WORDPRESS_DB_HOST" | cut -d: -f2)

# Check for ANY tables (not just wp_options) — the import plugin may
# use a different prefix (e.g. lch_options instead of wp_options).
TABLE_COUNT=$(mysql -h"$DB_HOST_ONLY" -P"$DB_PORT_ONLY" -u"$WORDPRESS_DB_USER" -p"$WORDPRESS_DB_PASSWORD" "$WORDPRESS_DB_NAME" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$WORDPRESS_DB_NAME';" 2>/dev/null || echo "0")

if [[ "$TABLE_COUNT" -lt 2 ]]; then
    echo "Installing WordPress via WP-CLI..."
    ADMIN_USER="${WP_ADMIN_USER:-admin}"
    ADMIN_PASS="${WP_ADMIN_PASSWORD:-admin}"
    ADMIN_EMAIL="${WP_ADMIN_EMAIL:-admin@clones.betaweb.ai}"
    SITE_URL="http://localhost"

    wp core install \
        --url="$SITE_URL" \
        --title="WordPress Clone" \
        --admin_user="$ADMIN_USER" \
        --admin_password="$ADMIN_PASS" \
        --admin_email="$ADMIN_EMAIL" \
        --skip-email \
        --allow-root \
        --path=/var/www/html

    # Create uploads directory (wp core install doesn't create it)
    mkdir -p /var/www/html/wp-content/uploads/custom-migrator/tmp
    chown -R www-data:www-data /var/www/html/wp-content/uploads

    echo "WordPress installed successfully"
else
    echo "WordPress already installed"
fi

# Install custom-migrator plugin if not already present
if [[ ! -d /var/www/html/wp-content/plugins/custom-migrator ]] && [[ -f /plugin.zip ]]; then
    echo "Installing custom-migrator plugin..."
    wp plugin install /plugin.zip --activate --allow-root --path=/var/www/html
    echo "custom-migrator plugin installed and activated"
elif [[ -d /var/www/html/wp-content/plugins/custom-migrator ]]; then
    echo "custom-migrator plugin already exists"
    # Ensure it's activated
    wp plugin activate custom-migrator --allow-root --path=/var/www/html 2>/dev/null || true
else
    echo "WARNING: /plugin.zip not found, custom-migrator plugin not installed"
fi

echo "Starting Apache in foreground..."
exec apache2-foreground
