<?php

if (!defined('ABSPATH')) {
    exit;
}

class Custom_Migrator_API {
    
    public static function init() {
        // High priority to ensure we handle the request before WordPress installation check might redirect
        add_action('rest_api_init', array(__CLASS__, 'register_routes'), 5);
        
        // Disable the "WordPress is not installed" redirect for our migration API calls
        if (isset($_SERVER['REQUEST_URI']) && strpos($_SERVER['REQUEST_URI'], 'custom-migrator/v1') !== false) {
            add_filter('wp_die_handler', function() { return '__return_null'; });
            remove_action('admin_init', 'wp_redirect_admin_locations', 1000);
        }
    }
    
    public static function register_routes() {
        // Export endpoint
        register_rest_route('custom-migrator/v1', '/export', array(
            'methods' => 'POST',
            'callback' => array(__CLASS__, 'handle_export'),
            'permission_callback' => array(__CLASS__, 'verify_api_key')
        ));
        
        // Import endpoint
        register_rest_route('custom-migrator/v1', '/import', array(
            'methods' => 'POST',
            'callback' => array(__CLASS__, 'handle_import'),
            'permission_callback' => array(__CLASS__, 'verify_api_key')
        ));
        
        // Status endpoint
        register_rest_route('custom-migrator/v1', '/status', array(
            'methods' => 'GET',
            'callback' => array(__CLASS__, 'handle_status'),
            'permission_callback' => array(__CLASS__, 'verify_api_key')
        ));
    }
    
    public static function verify_api_key($request) {
        $provided_key = $request->get_header('X-Migrator-Key');
        $stored_key = get_option('custom_migrator_api_key');
        
        if (empty($provided_key) || empty($stored_key)) {
            return new WP_Error(
                'no_api_key',
                'API key is missing',
                array('status' => 401)
            );
        }
        
        if (!hash_equals($stored_key, $provided_key)) {
            return new WP_Error(
                'invalid_api_key',
                'Invalid API key',
                array('status' => 403)
            );
        }
        
        return true;
    }
    
    public static function handle_export($request) {
        $exporter = Custom_Migrator_Exporter::get_instance();
        $result = $exporter->export();
        
        if ($result['success']) {
            return new WP_REST_Response($result, 200);
        } else {
            return new WP_Error(
                'export_failed',
                $result['error'],
                array('status' => 500)
            );
        }
    }
    
    public static function handle_import($request) {
        $params = $request->get_json_params();
        
        if (empty($params)) {
            $params = $request->get_body_params();
        }
        
        $archive_url = isset($params['archive_url']) ? $params['archive_url'] : null;
        $archive_path = isset($params['archive_path']) ? $params['archive_path'] : null;
        $public_url = isset($params['public_url']) ? $params['public_url'] : null;
        $admin_user = isset($params['admin_user']) ? $params['admin_user'] : null;
        $admin_password = isset($params['admin_password']) ? $params['admin_password'] : null;
        $preserve_themes = isset($params['preserve_themes']) ? (bool)$params['preserve_themes'] : false;
        $preserve_plugins = isset($params['preserve_plugins']) ? (bool)$params['preserve_plugins'] : false;
        
        // Check for file upload
        $files = $request->get_file_params();
        if (!empty($files['archive'])) {
            $uploaded = $files['archive'];
            if ($uploaded['error'] === UPLOAD_ERR_OK) {
                $upload_dir = wp_upload_dir();
                $temp_path = $upload_dir['basedir'] . '/custom-migrator/tmp/' . basename($uploaded['name']);
                move_uploaded_file($uploaded['tmp_name'], $temp_path);
                $archive_path = $temp_path;
            }
        }
        
        if (!$archive_url && !$archive_path) {
            return new WP_Error(
                'no_archive',
                'No archive provided. Use archive_url, archive_path, or upload a file.',
                array('status' => 400)
            );
        }
        
        $importer = Custom_Migrator_Importer::get_instance();
        $result = $importer->import($archive_path, $archive_url, $public_url, $admin_user, $admin_password, $preserve_themes, $preserve_plugins);
        
        if ($result['success']) {
            return new WP_REST_Response($result, 200);
        } else {
            return new WP_Error(
                'import_failed',
                $result['error'],
                array('status' => 500)
            );
        }
    }
    
    public static function handle_status($request) {
        $upload_dir = wp_upload_dir();
        $logs_dir = $upload_dir['basedir'] . '/custom-migrator/logs';
        
        $export_log = $logs_dir . '/export.log';
        $import_log = $logs_dir . '/import.log';
        
        $status = array(
            'plugin_version' => CUSTOM_MIGRATOR_VERSION,
            'import_allowed' => (bool) get_option('custom_migrator_allow_import', false),
            'logs' => array()
        );
        
        if (file_exists($export_log)) {
            $status['logs']['export'] = file_get_contents($export_log);
        }
        
        if (file_exists($import_log)) {
            $status['logs']['import'] = file_get_contents($import_log);
        }
        
        return new WP_REST_Response($status, 200);
    }
}
