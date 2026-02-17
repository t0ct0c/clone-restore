<?php
/**
 * Plugin Name: Custom WP Migrator
 * Description: HTTP-based WordPress migration tool for automated cloning
 * Version: 1.0.0
 * Author: charles
 */

if (!defined('ABSPATH')) {
    exit;
}

define('CUSTOM_MIGRATOR_VERSION', '1.0.0');
define('CUSTOM_MIGRATOR_PLUGIN_DIR', plugin_dir_path(__FILE__));
define('CUSTOM_MIGRATOR_PLUGIN_URL', plugin_dir_url(__FILE__));

// Include core classes
require_once CUSTOM_MIGRATOR_PLUGIN_DIR . 'includes/class-exporter.php';
require_once CUSTOM_MIGRATOR_PLUGIN_DIR . 'includes/class-importer.php';
require_once CUSTOM_MIGRATOR_PLUGIN_DIR . 'includes/class-api.php';
require_once CUSTOM_MIGRATOR_PLUGIN_DIR . 'includes/class-settings.php';

// Initialize plugin
add_action('plugins_loaded', 'custom_migrator_init');

function custom_migrator_init() {
    // Initialize API endpoints
    Custom_Migrator_API::init();

    // Initialize settings
    Custom_Migrator_Settings::init();

    // Enable Application Passwords over HTTP for development/testing
    // This is required when WordPress is running without HTTPS
    add_filter('wp_is_application_passwords_available', '__return_true');
}

// Activation hook
register_activation_hook(__FILE__, 'custom_migrator_activate');

function custom_migrator_activate() {
    // Create necessary directories
    $upload_dir = wp_upload_dir();
    $base_dir = $upload_dir['basedir'] . '/custom-migrator';
    
    $directories = array(
        $base_dir,
        $base_dir . '/tmp',
        $base_dir . '/exports',
        $base_dir . '/logs'
    );
    
    foreach ($directories as $dir) {
        if (!file_exists($dir)) {
            wp_mkdir_p($dir);
            
            // Add index.php for security
            $index_file = $dir . '/index.php';
            if (!file_exists($index_file)) {
                file_put_contents($index_file, '<?php // Silence is golden');
            }
        }
    }
    
    // Generate default API key if not exists
    if (!get_option('custom_migrator_api_key')) {
        update_option('custom_migrator_api_key', wp_generate_password(32, false));
    }
    
    // Ensure .htaccess exists with proper rewrite rules for REST API
    $htaccess_file = ABSPATH . '.htaccess';
    $htaccess_content = "# BEGIN WordPress\n<IfModule mod_rewrite.c>\nRewriteEngine On\nRewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]\nRewriteBase /\nRewriteRule ^index\\.php$ - [L]\nRewriteCond %{REQUEST_FILENAME} !-f\nRewriteCond %{REQUEST_FILENAME} !-d\nRewriteRule . /index.php [L]\n</IfModule>\n# END WordPress\n";
    
    if (!file_exists($htaccess_file) || filesize($htaccess_file) === 0) {
        file_put_contents($htaccess_file, $htaccess_content);
    }
    
    // Flush rewrite rules to ensure REST API works
    flush_rewrite_rules();
}

// Deactivation hook
register_deactivation_hook(__FILE__, 'custom_migrator_deactivate');

function custom_migrator_deactivate() {
    // Cleanup on deactivation if needed
}
