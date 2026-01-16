FROM wordpress:latest

# Install required tools
RUN apt-get update && apt-get install -y \
    zip \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Copy custom entrypoint that fixes MPM configuration
COPY docker/custom-entrypoint.sh /usr/local/bin/custom-entrypoint.sh
RUN chmod +x /usr/local/bin/custom-entrypoint.sh

# Copy custom migrator plugin
COPY plugin /usr/src/wordpress/wp-content/plugins/custom-migrator

# Copy custom theme (source identifier)
COPY custom-theme /usr/src/wordpress/wp-content/themes/source-theme

# Create initialization script
RUN echo '#!/bin/bash\n\
set -e\n\
# Wait for WordPress to be copied\n\
while [ ! -f /var/www/html/wp-config.php ]; do sleep 1; done\n\
# Fix .htaccess\n\
cat > /var/www/html/.htaccess << "EOF"\n\
# BEGIN WordPress\n\
<IfModule mod_rewrite.c>\n\
RewriteEngine On\n\
RewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]\n\
RewriteBase /\n\
RewriteRule ^index\\.php$ - [L]\n\
RewriteCond %{REQUEST_FILENAME} !-f\n\
RewriteCond %{REQUEST_FILENAME} !-d\n\
RewriteRule . /index.php [L]\n\
</IfModule>\n\
# END WordPress\n\
EOF\n\
# Create plugin directories\n\
mkdir -p /var/www/html/wp-content/uploads/custom-migrator/{tmp,exports,logs}\n\
chown -R www-data:www-data /var/www/html/wp-content\n\
chmod -R 755 /var/www/html/wp-content/uploads/custom-migrator\n\
' > /usr/local/bin/wp-init.sh && chmod +x /usr/local/bin/wp-init.sh

# Run init script in background on startup
RUN echo '(/usr/local/bin/wp-init.sh &)' >> /usr/local/bin/docker-entrypoint.sh

# Set custom entrypoint that fixes MPM before WordPress entrypoint
ENTRYPOINT ["/usr/local/bin/custom-entrypoint.sh"]
CMD ["apache2-foreground"]

EXPOSE 80
