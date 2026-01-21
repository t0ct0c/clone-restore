#!/bin/bash
set -e

# Fix Apache configuration
echo "Configuring Apache..."
a2dismod mpm_event mpm_worker 2>/dev/null || true
a2enmod mpm_prefork 2>/dev/null || true
# Disable mod_deflate to prevent "download file" issues behind reverse proxy
# We use -f to force it even if it's already disabled or has dependencies
a2dismod deflate -f 2>/dev/null || true
echo "Apache configuration updated."

# Inject reverse proxy configuration into wp-config.php
cat > /tmp/inject-proxy.php << 'EOF'
<?php
$file = '/var/www/html/wp-config.php';
if (!file_exists($file)) exit;
$content = file_get_contents($file);
if (strpos($content, 'WP_REVERSE_PROXY') === false) {
    $proxy_config = "\n/* WP_REVERSE_PROXY: Handle reverse proxy path-based routing */\n" .
                    "if (isset(\$_SERVER['HTTP_X_FORWARDED_PREFIX'])) { \$prefix = rtrim(\$_SERVER['HTTP_X_FORWARDED_PREFIX'], '/'); } else { \$prefix = ''; }\n" .
                    "\$host = isset(\$_SERVER['HTTP_X_FORWARDED_HOST']) ? \$_SERVER['HTTP_X_FORWARDED_HOST'] : (isset(\$_SERVER['HTTP_HOST']) ? \$_SERVER['HTTP_HOST'] : 'localhost');\n" .
                    "\$proto = isset(\$_SERVER['HTTP_X_FORWARDED_PROTO']) ? \$_SERVER['HTTP_X_FORWARDED_PROTO'] : 'http';\n" .
                    "if (\$proto === 'https') { \$_SERVER['HTTPS'] = 'on'; }\n" .
                    "define('WP_HOME', \$proto . '://' . \$host . \$prefix);\n" .
                    "define('WP_SITEURL', \$proto . '://' . \$host . \$prefix);\n" .
                    "define('COOKIEPATH', \$prefix . '/');\n" .
                    "define('SITECOOKIEPATH', \$prefix . '/');\n" .
                    "define('ADMIN_COOKIE_PATH', \$prefix . '/wp-admin');\n" .
                    "define('FORCE_SSL_ADMIN', (\$proto === 'https'));\n";
    
    // Try to find the best place to insert the config
    if (strpos($content, "/* That's all, stop editing!") !== false) {
        $content = str_replace("/* That's all, stop editing!", $proxy_config . "/* That's all, stop editing!", $content);
    } else {
        $content = preg_replace('/^<\?php/', '<?php' . $proxy_config, $content);
    }
    file_put_contents($file, $content);
}
EOF

cat > /tmp/inject-proxy-config.sh << 'INJECT_EOF'
#!/bin/bash
# Wait for wp-config.php to be created by the official entrypoint or our auto-install script
for i in {1..30}; do
    if [ -f /var/www/html/wp-config.php ]; then
        php /tmp/inject-proxy.php
        echo "Reverse proxy configuration injected into wp-config.php"
        
        # Handle subpath symlink if WP_SUBPATH is set
        if [ -n "$WP_SUBPATH" ] && [ "$WP_SUBPATH" != "/" ]; then
            SUBPATH_DIR="/var/www/html${WP_SUBPATH}"
            PARENT_DIR=$(dirname "$SUBPATH_DIR")
            mkdir -p "$PARENT_DIR"
            if [ ! -L "$SUBPATH_DIR" ]; then
                ln -s /var/www/html "$SUBPATH_DIR"
                echo "Created subpath symlink: $SUBPATH_DIR -> /var/www/html"
            fi
        fi
        break
    fi
    sleep 1
done
INJECT_EOF

chmod +x /tmp/inject-proxy-config.sh
(/tmp/inject-proxy-config.sh > /var/log/proxy-inject.log 2>&1 &)

# Start WordPress initialization in background
(/usr/local/bin/wp-auto-install.sh > /var/log/wp-init.log 2>&1 &)

# Run original WordPress entrypoint
exec docker-entrypoint.sh "$@"
