<?php

if (!defined('ABSPATH')) {
    exit;
}

class Custom_Migrator_Settings {
    
    public static function init() {
        add_action('admin_menu', array(__CLASS__, 'add_admin_menu'));
        add_action('admin_init', array(__CLASS__, 'register_settings'));
    }
    
    public static function add_admin_menu() {
        add_options_page(
            'Custom Migrator Settings',
            'Custom Migrator',
            'manage_options',
            'custom-migrator-settings',
            array(__CLASS__, 'render_settings_page')
        );
    }
    
    public static function register_settings() {
        register_setting('custom_migrator_settings', 'custom_migrator_api_key');
        register_setting('custom_migrator_settings', 'custom_migrator_allow_import');
    }
    
    public static function render_settings_page() {
        if (!current_user_can('manage_options')) {
            return;
        }
        
        $api_key = get_option('custom_migrator_api_key');
        $allow_import = get_option('custom_migrator_allow_import', false);
        
        ?>
        <div class="wrap">
            <h1>Custom Migrator Settings</h1>
            
            <form method="post" action="options.php">
                <?php settings_fields('custom_migrator_settings'); ?>
                
                <table class="form-table">
                    <tr>
                        <th scope="row">
                            <label for="custom_migrator_api_key">API Key</label>
                        </th>
                        <td>
                            <input type="text" 
                                   id="custom_migrator_api_key" 
                                   name="custom_migrator_api_key" 
                                   value="<?php echo esc_attr($api_key); ?>" 
                                   class="regular-text"
                                   readonly />
                            <p class="description">
                                Use this key in the X-Migrator-Key header for API requests.
                            </p>
                        </td>
                    </tr>
                    
                    <tr>
                        <th scope="row">
                            <label for="custom_migrator_allow_import">Allow Import</label>
                        </th>
                        <td>
                            <label>
                                <input type="checkbox" 
                                       id="custom_migrator_allow_import" 
                                       name="custom_migrator_allow_import" 
                                       value="1" 
                                       <?php checked($allow_import, true); ?> />
                                Enable import functionality (WARNING: This will overwrite existing site data)
                            </label>
                            <p class="description" style="color: red;">
                                <strong>DANGER:</strong> Enabling this allows the site to be completely overwritten via API.
                                Only enable on non-production target instances.
                            </p>
                        </td>
                    </tr>
                </table>
                
                <?php submit_button(); ?>
            </form>
            
            <hr />
            
            <h2>API Endpoints</h2>
            <table class="widefat">
                <thead>
                    <tr>
                        <th>Endpoint</th>
                        <th>Method</th>
                        <th>Description</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><code><?php echo rest_url('custom-migrator/v1/export'); ?></code></td>
                        <td>POST</td>
                        <td>Export site as zip archive</td>
                    </tr>
                    <tr>
                        <td><code><?php echo rest_url('custom-migrator/v1/import'); ?></code></td>
                        <td>POST</td>
                        <td>Import site from archive (requires "Allow Import" enabled)</td>
                    </tr>
                    <tr>
                        <td><code><?php echo rest_url('custom-migrator/v1/status'); ?></code></td>
                        <td>GET</td>
                        <td>Get plugin status and logs</td>
                    </tr>
                </tbody>
            </table>
            
            <h3>Example Usage</h3>
            <pre style="background: #f5f5f5; padding: 15px; border: 1px solid #ddd;">
# Export from source
curl -X POST \
  -H "X-Migrator-Key: <?php echo esc_html($api_key); ?>" \
  <?php echo rest_url('custom-migrator/v1/export'); ?>

# Import to target (using URL)
curl -X POST \
  -H "X-Migrator-Key: YOUR_TARGET_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"archive_url": "http://wp_source/wp-content/uploads/custom-migrator/exports/migration-20240114120000.zip"}' \
  http://wp_target/wp-json/custom-migrator/v1/import
            </pre>
        </div>
        <?php
    }
}
