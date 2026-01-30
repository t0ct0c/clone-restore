#!/bin/bash
set -e

# Fix Apache MPM configuration
echo "Fixing Apache MPM configuration..."
a2dismod mpm_event mpm_worker 2>/dev/null || true
a2enmod mpm_prefork 2>/dev/null || true
echo "MPM configuration fixed."

# Inject reverse proxy configuration and Application Passwords support into wp-config.php
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
                    "if (\$prefix) {\n" .
                    "    if (strpos(\$_SERVER['REQUEST_URI'], \$prefix) !== 0) {\n" .
                    "        \$_SERVER['REQUEST_URI'] = \$prefix . \$_SERVER['REQUEST_URI'];\n" .
                    "    }\n" .
                    "}\n" .
                    "define('WP_HOME', \$proto . '://' . \$host . \$prefix);\n" .
                    "define('WP_SITEURL', \$proto . '://' . \$host . \$prefix);\n" .
                    "define('COOKIEPATH', \$prefix . '/');\n" .
                    "define('SITECOOKIEPATH', \$prefix . '/');\n" .
                    "define('ADMIN_COOKIE_PATH', \$prefix . '/wp-admin');\n\n" .
                    "/* Enable Application Passwords over HTTP for development */\n" .
                    "define('WP_ENVIRONMENT_TYPE', 'local');\n";
    $content = str_replace("/* That's all, stop editing!", $proxy_config . "/* That's all, stop editing!", $content);
    file_put_contents($file, $content);
}
EOF

cat > /tmp/inject-proxy-config.sh << 'INJECT_EOF'
#!/bin/bash
for i in {1..30}; do
    if [ -f /var/www/html/wp-config.php ]; then
        php /tmp/inject-proxy.php
        echo "Reverse proxy configuration injected into wp-config.php"
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
