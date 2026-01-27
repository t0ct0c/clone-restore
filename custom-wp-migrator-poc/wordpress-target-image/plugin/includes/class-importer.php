<?php

if (!defined('ABSPATH')) {
    exit;
}

class Custom_Migrator_Importer {
    
    private static $instance = null;
    
    public static function get_instance() {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }
    
    public function import($archive_path = null, $archive_url = null, $target_url_override = null, $admin_user = null, $admin_password = null, $preserve_themes = false, $preserve_plugins = false) {
        try {
            $this->log('Starting import...');
            
            // Enable maintenance mode
            $this->enable_maintenance_mode();
            
            // Get archive
            if ($archive_url) {
                $this->log('Downloading archive from URL...');
                $archive_path = $this->download_archive($archive_url);
            } elseif (!$archive_path || !file_exists($archive_path)) {
                throw new Exception('No valid archive provided');
            }
            
            // Extract archive
            $this->log('Extracting archive...');
            $extract_dir = $this->extract_archive($archive_path);
            
            // Import database
            $this->log('Importing database...');
            $this->import_database($extract_dir . '/database.sql', $target_url_override);
            
            // Set URL constants in wp-config.php to prevent redirect loops
            $this->log('Setting URL constants in wp-config.php...');
            if ($target_url_override) {
                $this->set_url_constants_in_config($target_url_override);
            }
            
            // Restore files
            $this->log('Restoring files...');
            $this->restore_files($extract_dir . '/wp-content', $preserve_themes, $preserve_plugins);
            
            // Create or update admin user if credentials provided
            if ($admin_user && $admin_password) {
                $this->log("Ensuring admin user exists: $admin_user");
                $this->create_or_update_admin_user($admin_user, $admin_password);
            }
            
            // Fix .htaccess for subdirectory installations (clones)
            if ($target_url_override) {
                $this->fix_htaccess_for_subdirectory($target_url_override);
            }
            
            // Disable SiteGround plugins that cause redirect loops in subdirectory paths
            $this->disable_siteground_plugins();
            
            // Cleanup
            $this->cleanup_temp_dir($extract_dir);
            if ($archive_url) {
                unlink($archive_path);
            }
            
            // Disable maintenance mode
            $this->disable_maintenance_mode();
            
            $this->log('Import completed successfully.');
            
            return array(
                'success' => true,
                'message' => 'Site imported successfully'
            );
            
        } catch (Exception $e) {
            $this->disable_maintenance_mode();
            $this->log('Import failed: ' . $e->getMessage());
            return array(
                'success' => false,
                'error' => $e->getMessage()
            );
        }
    }
    
    private function download_archive($url) {
        $upload_dir = wp_upload_dir();
        $temp_dir = $upload_dir['basedir'] . '/custom-migrator/tmp';
        $temp_file = $temp_dir . '/import-' . uniqid() . '.zip';
        
        $response = wp_remote_get($url, array(
            'timeout' => 300,
            'stream' => true,
            'filename' => $temp_file
        ));
        
        if (is_wp_error($response)) {
            throw new Exception('Failed to download archive: ' . $response->get_error_message());
        }
        
        return $temp_file;
    }
    
    private function extract_archive($archive_path) {
        $upload_dir = wp_upload_dir();
        $extract_dir = $upload_dir['basedir'] . '/custom-migrator/tmp/import-' . uniqid();
        
        if (!wp_mkdir_p($extract_dir)) {
            throw new Exception('Could not create extraction directory');
        }
        
        $zip = new ZipArchive();
        if ($zip->open($archive_path) !== true) {
            throw new Exception('Could not open archive');
        }
        
        $zip->extractTo($extract_dir);
        $zip->close();
        
        return $extract_dir;
    }
    
    private function import_database($db_file, $target_url_override = null) {
        global $wpdb;
        
        if (!file_exists($db_file)) {
            throw new Exception('Database file not found in archive');
        }
        
        $sql = file_get_contents($db_file);
        
        if (empty($sql)) {
            throw new Exception('Database file is empty');
        }
        
        // MySQL: Drop and recreate tables
        $this->log('Dropping existing tables...');
        $this->drop_all_tables();
        
        // Detect table prefix from SQL dump (CRITICAL for site detection)
        $detected_prefix = $this->detect_prefix_from_sql($sql);
        if ($detected_prefix) {
            $this->log("Detected table prefix from source: $detected_prefix");
            $this->update_wp_config_prefix($detected_prefix);
            // Refresh wpdb prefix for current request
            $wpdb->prefix = $detected_prefix;
            $wpdb->set_prefix($detected_prefix);
        }

        // Extract old URL before importing (for wp search-replace later)
        $old_url = $this->extract_url_from_sql($sql, $detected_prefix ? $detected_prefix : 'wp_');
        if ($old_url) {
            $this->log("Extracted source URL from database: $old_url");
        }
        
        // Import the SQL directly
        $this->log('Executing SQL import...');
        $this->execute_sql($sql);
        
        // Use WP-CLI for search-replace if available (handles serialization)
        // Use override if provided, otherwise fallback to internal site URL
        $new_url = $target_url_override ? $target_url_override : get_site_url();
        $new_url = rtrim($new_url, '/');
        
        if ($old_url && $old_url !== $new_url) {
            $this->log("Running WP-CLI search-replace: $old_url -> $new_url");
            
            // Run search-replace on all tables. WP-CLI handles serialization correctly.
            $cmd = "wp search-replace " . escapeshellarg($old_url) . " " . escapeshellarg($new_url) . " --all-tables --path=" . escapeshellarg(ABSPATH) . " --allow-root 2>&1";
            exec($cmd, $output, $return_var);
            
            if ($return_var !== 0) {
                $this->log("WP-CLI search-replace failed (code $return_var): " . implode("\n", $output));
                // Fallback to basic replacement if WP-CLI fails (though less reliable for design)
                $this->replace_urls_manually($old_url, $new_url);
            } else {
                $this->log("WP-CLI search-replace completed successfully.");
            }
        }
        
        // Regenerate Elementor CSS if it exists (CRITICAL for design)
        $this->log('Checking for Elementor styles...');
        if (is_dir(WP_PLUGIN_DIR . '/elementor')) {
            $this->log('Regenerating Elementor CSS...');
            exec("wp elementor flush-css --path=" . escapeshellarg(ABSPATH) . " --allow-root 2>&1");
        }
    }

    private function execute_sql($sql) {
        global $wpdb;
        
        // Split into individual queries
        $queries = array_filter(
            array_map('trim', explode(";\n", $sql)),
            function($query) {
                return !empty($query) && strpos($query, '--') !== 0;
            }
        );
        
        // Execute queries
        foreach ($queries as $query) {
            $result = $wpdb->query($query);
            if ($result === false && !empty($wpdb->last_error)) {
                $this->log('Query warning: ' . $wpdb->last_error);
            }
        }
    }

    private function replace_urls_manually($old_url, $new_url) {
        global $wpdb;
        $this->log("Running manual URL replacement: $old_url -> $new_url");
        $this->log("Using table prefix: {$wpdb->prefix}");
        
        // Use current prefix to build table names
        $prefix = $wpdb->prefix;
        $tables = array(
            $prefix . 'options' => array('option_value'),
            $prefix . 'posts' => array('post_content', 'guid'),
            $prefix . 'postmeta' => array('meta_value')
        );
        
        foreach ($tables as $table => $columns) {
            foreach ($columns as $column) {
                $result = $wpdb->query($wpdb->prepare(
                    "UPDATE `$table` SET `$column` = REPLACE(`$column`, %s, %s)",
                    $old_url,
                    $new_url
                ));
                $this->log("Updated $table.$column: $result rows affected");
            }
        }
        
        // Also update siteurl and home directly to be sure
        $wpdb->query($wpdb->prepare(
            "UPDATE `{$prefix}options` SET `option_value` = %s WHERE `option_name` = 'siteurl'",
            $new_url
        ));
        $wpdb->query($wpdb->prepare(
            "UPDATE `{$prefix}options` SET `option_value` = %s WHERE `option_name` = 'home'",
            $new_url
        ));
        $this->log("Explicitly set siteurl and home to: $new_url");
    }
    
    private function drop_all_tables() {
        global $wpdb;
        
        // Get all tables with WordPress prefix (MySQL)
        $tables = $wpdb->get_col("SHOW TABLES LIKE '{$wpdb->prefix}%'");
        
        foreach ($tables as $table) {
            $wpdb->query("DROP TABLE IF EXISTS `$table`");
            $this->log("Dropped table: $table");
        }
    }
    
    private function detect_prefix_from_sql($sql) {
        // Look for CREATE TABLE or INSERT INTO commands to find the prefix
        // We look for common tables like users or options
        if (preg_match("/(?:CREATE TABLE|INSERT INTO)\s+`([^`]+)options`/", $sql, $matches)) {
            return $matches[1];
        }
        return null;
    }

    private function update_wp_config_prefix($new_prefix) {
        $config_file = ABSPATH . 'wp-config.php';
        if (!file_exists($config_file)) return;

        $content = file_get_contents($config_file);
        
        // Handle both simple strings and getenv_docker patterns
        $patterns = [
            "/\\\$table_prefix\s*=\s*['\"][^\"']*['\"];/",
            "/\\\$table_prefix\s*=\s*getenv_docker\(['\"]WORDPRESS_TABLE_PREFIX['\"]\s*,\s*['\"][^\"']*['\"]\);/"
        ];
        
        $replacement = "\$table_prefix = '$new_prefix';";
        
        $updated = false;
        foreach ($patterns as $pattern) {
            if (preg_match($pattern, $content)) {
                $this->log("Updating wp-config.php table prefix to: $new_prefix (matched pattern)");
                $content = preg_replace($pattern, $replacement, $content);
                $updated = true;
                break;
            }
        }
        
        if ($updated) {
            file_put_contents($config_file, $content);
        } else {
            $this->log("Warning: Could not find table_prefix definition in wp-config.php to update");
        }
    }

    private function extract_url_from_sql($sql, $prefix = 'wp_') {
        // Extract siteurl from options table using detected prefix
        $table_name = $prefix . 'options';
        if (preg_match("/INSERT INTO [^`]*`$table_name`[^;]*'siteurl'[^']*'([^']+)'/", $sql, $matches)) {
            return $matches[1];
        }
        return null;
    }
    
    private function set_url_constants_in_config($target_url) {
        $config_file = ABSPATH . 'wp-config.php';
        if (!file_exists($config_file)) {
            $this->log("Warning: wp-config.php not found");
            return;
        }

        $content = file_get_contents($config_file);
        $this->log("Setting WP_HOME and WP_SITEURL to: $target_url");
        
        // Remove any existing WP_HOME/WP_SITEURL definitions
        $patterns = array(
            "/define\\s*\\(\\s*['\"]WP_HOME['\"]\\s*,\\s*[^;]+\\s*\\)\\s*;[\\r\\n]*/",
            "/define\\s*\\(\\s*['\"]WP_SITEURL['\"]\\s*,\\s*[^;]+\\s*\\)\\s*;[\\r\\n]*/"
        );
        
        foreach ($patterns as $pattern) {
            $content = preg_replace($pattern, '', $content);
        }
        
        // Find require_once wp-settings.php line
        $wp_settings_pattern = "/require_once.*wp-settings\\.php.*;/";
        
        if (preg_match($wp_settings_pattern, $content, $matches, PREG_OFFSET_CAPTURE)) {
            $insert_position = $matches[0][1];
            
            // Build the constants to insert
            $constants = "\n/* URL constants set by migrator - DO NOT REMOVE */\n";
            $constants .= "define('WP_HOME', '" . addslashes($target_url) . "');\n";
            $constants .= "define('WP_SITEURL', '" . addslashes($target_url) . "');\n";
            $constants .= "/* End migrator constants */\n\n";
            
            // Insert before wp-settings.php
            $content = substr_replace($content, $constants, $insert_position, 0);
            
            $result = file_put_contents($config_file, $content);
            if ($result !== false) {
                $this->log("Successfully set URL constants in wp-config.php");
            } else {
                $this->log("ERROR: Failed to write wp-config.php");
                return;
            }
        } else {
            $this->log("ERROR: Could not find wp-settings.php require line in wp-config.php");
            return;
        }
        
        // Create must-use plugin to disable canonical redirects
        $mu_plugins_dir = WP_CONTENT_DIR . '/mu-plugins';
        if (!file_exists($mu_plugins_dir)) {
            mkdir($mu_plugins_dir, 0755, true);
            $this->log("Created mu-plugins directory");
        }
        
        $mu_plugin_file = $mu_plugins_dir . '/force-url-constants.php';
        $mu_plugin_content = "<?php\n";
        $mu_plugin_content .= "/**\n";
        $mu_plugin_content .= " * Plugin Name: Force URL Constants\n";
        $mu_plugin_content .= " * Description: Prevents redirect loops by disabling canonical redirects\n";
        $mu_plugin_content .= " * Version: 1.0\n";
        $mu_plugin_content .= " */\n\n";
        $mu_plugin_content .= "remove_action('template_redirect', 'redirect_canonical');\n";
        $mu_plugin_content .= "add_filter('option_home', function() { return WP_HOME; });\n";
        $mu_plugin_content .= "add_filter('option_siteurl', function() { return WP_SITEURL; });\n";
        
        $result = file_put_contents($mu_plugin_file, $mu_plugin_content);
        if ($result !== false) {
            $this->log("Created must-use plugin to prevent redirect loops");
        } else {
            $this->log("ERROR: Failed to create must-use plugin");
        }
    }
    
    private function replace_urls_in_sql($sql, $old_url, $new_url) {
        // Simple string replacement for URLs
        // Note: This is a basic implementation. For serialized data, you'd need more complex logic
        $sql = str_replace($old_url, $new_url, $sql);
        
        // Also handle escaped versions
        $old_url_escaped = str_replace('/', '\\/', $old_url);
        $new_url_escaped = str_replace('/', '\\/', $new_url);
        $sql = str_replace($old_url_escaped, $new_url_escaped, $sql);
        
        return $sql;
    }
    
    private function restore_files($source_wp_content, $preserve_themes = false, $preserve_plugins = false) {
        if (!file_exists($source_wp_content)) {
            throw new Exception('wp-content directory not found in archive');
        }
        
        $dest_wp_content = WP_CONTENT_DIR;
        
        // Always preserve custom-migrator plugin
        $essential_plugins = array('custom-migrator');
        
        // Backup essential plugins before restore
        $plugin_backups = array();
        foreach ($essential_plugins as $plugin) {
            $plugin_path = $dest_wp_content . '/plugins/' . $plugin;
            if (file_exists($plugin_path)) {
                $backup_path = sys_get_temp_dir() . '/wp_plugin_backup_' . $plugin . '_' . uniqid();
                $this->recursive_copy($plugin_path, $backup_path);
                $plugin_backups[$plugin] = $backup_path;
                $this->log("Backed up essential plugin: $plugin");
            }
        }
        
        // Backup target themes if preserve_themes is true
        $theme_backup_path = null;
        if ($preserve_themes) {
            $themes_dest = $dest_wp_content . '/themes';
            if (file_exists($themes_dest)) {
                $theme_backup_path = sys_get_temp_dir() . '/wp_themes_backup_' . uniqid();
                $this->recursive_copy($themes_dest, $theme_backup_path);
                $this->log('Backed up target themes (preserve_themes=true)');
            }
        }
        
        // Backup target plugins if preserve_plugins is true
        $plugins_backup_path = null;
        if ($preserve_plugins) {
            $plugins_dest = $dest_wp_content . '/plugins';
            if (file_exists($plugins_dest)) {
                $plugins_backup_path = sys_get_temp_dir() . '/wp_plugins_backup_' . uniqid();
                $this->recursive_copy($plugins_dest, $plugins_backup_path);
                $this->log('Backed up target plugins (preserve_plugins=true)');
            }
        }
        
        // Restore themes
        if (!$preserve_themes) {
            $themes_src = $source_wp_content . '/themes';
            $themes_dest = $dest_wp_content . '/themes';
            if (file_exists($themes_src)) {
                $this->log('Replacing themes from source (preserve_themes=false)...');
                if (file_exists($themes_dest)) {
                    $this->recursive_delete($themes_dest);
                }
                $this->recursive_copy($themes_src, $themes_dest);
            }
        } else {
            $this->log('Keeping target themes (preserve_themes=true)');
        }
        
        // Restore plugins
        if (!$preserve_plugins) {
            $plugins_src = $source_wp_content . '/plugins';
            $plugins_dest = $dest_wp_content . '/plugins';
            if (file_exists($plugins_src)) {
                $this->log('Replacing plugins from source (preserve_plugins=false)...');
                if (file_exists($plugins_dest)) {
                    $this->recursive_delete($plugins_dest);
                }
                // Exclude custom-migrator to prevent duplicates
                $this->recursive_copy_exclude($plugins_src, $plugins_dest, array('custom-migrator', 'plugin'));
            }
        } else {
            $this->log('Keeping target plugins (preserve_plugins=true)');
        }
        
        // Restore uploads WITHOUT deleting (just overwrite to avoid permission issues)
        $uploads_src = $source_wp_content . '/uploads';
        $uploads_dest = $dest_wp_content . '/uploads';
        if (file_exists($uploads_src)) {
            $this->log('Copying uploads (overwriting existing files)...');
            $this->recursive_copy($uploads_src, $uploads_dest);
        }
        
        // Restore essential plugins (custom-migrator)
        foreach ($plugin_backups as $plugin => $backup_path) {
            $plugin_dest = $dest_wp_content . '/plugins/' . $plugin;
            $this->recursive_copy($backup_path, $plugin_dest);
            $this->recursive_delete($backup_path);
            $this->log("Restored essential plugin: $plugin");
        }
        
        // Clean up theme backup if it was created
        if ($theme_backup_path && file_exists($theme_backup_path)) {
            $this->recursive_delete($theme_backup_path);
        }
        
        // Clean up plugins backup if it was created
        if ($plugins_backup_path && file_exists($plugins_backup_path)) {
            $this->recursive_delete($plugins_backup_path);
        }
    }
    
    private function recursive_copy($src, $dest) {
        if (is_dir($src)) {
            if (!file_exists($dest)) {
                mkdir($dest, 0755, true);
            }
            
            $items = scandir($src);
            foreach ($items as $item) {
                if ($item === '.' || $item === '..') {
                    continue;
                }
                
                $this->recursive_copy($src . '/' . $item, $dest . '/' . $item);
            }
        } else {
            copy($src, $dest);
        }
    }
    
    private function recursive_copy_exclude($src, $dest, $exclude_dirs = array()) {
        if (!file_exists($dest)) {
            mkdir($dest, 0755, true);
        }
        
        $items = scandir($src);
        foreach ($items as $item) {
            if ($item === '.' || $item === '..') {
                continue;
            }
            
            // Skip excluded directories
            if (in_array($item, $exclude_dirs)) {
                $this->log("Skipping excluded directory during restore: $item");
                continue;
            }
            
            $src_path = $src . '/' . $item;
            $dest_path = $dest . '/' . $item;
            
            if (is_dir($src_path)) {
                $this->recursive_copy($src_path, $dest_path);
            } else {
                copy($src_path, $dest_path);
            }
        }
    }
    
    private function recursive_delete($dir) {
        if (!file_exists($dir)) {
            return;
        }
        
        $items = scandir($dir);
        foreach ($items as $item) {
            if ($item === '.' || $item === '..') {
                continue;
            }
            
            $path = $dir . '/' . $item;
            if (is_dir($path)) {
                $this->recursive_delete($path);
            } else {
                unlink($path);
            }
        }
        
        rmdir($dir);
    }
    
    private function cleanup_temp_dir($dir) {
        $this->recursive_delete($dir);
    }
    
    private function enable_maintenance_mode() {
        $file = ABSPATH . '.maintenance';
        file_put_contents($file, '<?php $upgrading = ' . time() . '; ?>');
    }
    
    private function disable_maintenance_mode() {
        $file = ABSPATH . '.maintenance';
        if (file_exists($file)) {
            unlink($file);
        }
    }
    
    private function create_or_update_admin_user($username, $password) {
        global $wpdb;
        $this->log("Creating/updating admin user: $username");
        
        // We use WP-CLI if available as it's cleaner, otherwise use SQL
        $cmd = "wp user create " . escapeshellarg($username) . " admin@example.com --user_pass=" . escapeshellarg($password) . " --role=administrator --path=" . escapeshellarg(ABSPATH) . " --allow-root 2>&1";
        exec($cmd, $output, $return_var);
        
        if ($return_var !== 0) {
            $this->log("WP-CLI user create failed or user exists, trying update...");
            $cmd = "wp user update " . escapeshellarg($username) . " --user_pass=" . escapeshellarg($password) . " --role=administrator --path=" . escapeshellarg(ABSPATH) . " --allow-root 2>&1";
            exec($cmd, $output, $return_var);
            
            if ($return_var !== 0) {
                $this->log("WP-CLI user update failed: " . implode("\n", $output));
                $this->log("Attempting manual SQL user update...");
                $this->manual_user_update($username, $password);
            } else {
                $this->log("Admin user updated successfully via WP-CLI.");
            }
        } else {
            $this->log("Admin user created successfully via WP-CLI.");
        }
    }

    private function manual_user_update($username, $password) {
        global $wpdb;
        $prefix = $wpdb->prefix;
        
        // Check if user exists
        $user = $wpdb->get_row($wpdb->prepare("SELECT ID FROM {$prefix}users WHERE user_login = %s", $username));
        
        if ($user) {
            $user_id = $user->ID;
            $wpdb->update(
                "{$prefix}users",
                array('user_pass' => wp_hash_password($password)),
                array('ID' => $user_id)
            );
            $this->log("Updated existing user ID $user_id password via SQL");
        } else {
            // Very basic insert if not exists (ideally should handle meta but administrator role is critical)
            $wpdb->insert(
                "{$prefix}users",
                array(
                    'user_login' => $username,
                    'user_pass' => wp_hash_password($password),
                    'user_email' => 'admin@example.com',
                    'user_registered' => date('Y-m-d H:i:s'),
                    'user_status' => 0,
                    'display_name' => $username
                )
            );
            $user_id = $wpdb->insert_id;
            
            // Add capabilities for administrator
            $caps = serialize(array('administrator' => true));
            $wpdb->insert(
                "{$prefix}usermeta",
                array(
                    'user_id' => $user_id,
                    'meta_key' => $prefix . 'capabilities',
                    'meta_value' => $caps
                )
            );
            $wpdb->insert(
                "{$prefix}usermeta",
                array(
                    'user_id' => $user_id,
                    'meta_key' => $prefix . 'user_level',
                    'meta_value' => '10'
                )
            );
            $this->log("Created new admin user ID $user_id via SQL");
        }
    }

    private function fix_htaccess_for_subdirectory($target_url) {
        $htaccess_file = ABSPATH . '.htaccess';
        
        // Extract path from URL
        $parsed_url = parse_url($target_url);
        $path = isset($parsed_url['path']) ? $parsed_url['path'] : '/';
        
        // Only apply fix for subdirectory installations
        if ($path === '/') {
            $this->log('Root installation detected, skipping .htaccess rewrite');
            return;
        }
        
        $this->log("Fixing .htaccess for subdirectory installation: $path");
        
        // Create minimal .htaccess with DirectoryIndex and proper PHP handling
        // This prevents download issues while avoiding redirect loops
        $htaccess_content = "# Minimal .htaccess for subdirectory WordPress\n";
        $htaccess_content .= "DirectoryIndex index.php index.html\n";
        $htaccess_content .= "\n";
        $htaccess_content .= "# Ensure PHP files are executed, not downloaded\n";
        $htaccess_content .= "<FilesMatch \\.php$>\n";
        $htaccess_content .= "    SetHandler application/x-httpd-php\n";
        $htaccess_content .= "</FilesMatch>\n";
        
        $result = file_put_contents($htaccess_file, $htaccess_content);
        if ($result !== false) {
            $this->log('Successfully created minimal .htaccess (DirectoryIndex only)');
        } else {
            $this->log('ERROR: Failed to write .htaccess');
        }
        
        // Set plain permalinks (no rewrite rules needed)
        // REST API will use query string format: /?rest_route=/endpoint
        global $wpdb;
        $wpdb->update(
            $wpdb->options,
            array('option_value' => ''),
            array('option_name' => 'permalink_structure'),
            array('%s'),
            array('%s')
        );
        $this->log('Set permalink structure to plain (no rewrite rules required)');
    }
    
    private function disable_siteground_plugins() {
        global $wpdb;
        
        // SiteGround plugins that cause redirect loops in subdirectory installations
        $siteground_plugins = array(
            'sg-cachepress/sg-cachepress.php',
            'sg-security/sg-security.php',
            'wordpress-starter/siteground-wizard.php',
            'siteground-optimizer/siteground-optimizer.php'
        );
        
        // Get current active plugins
        $active_plugins = get_option('active_plugins', array());
        $original_count = count($active_plugins);
        
        // Remove SiteGround plugins from active list
        $active_plugins = array_diff($active_plugins, $siteground_plugins);
        $active_plugins = array_values($active_plugins); // Re-index array
        
        $removed_count = $original_count - count($active_plugins);
        
        if ($removed_count > 0) {
            update_option('active_plugins', $active_plugins);
            $this->log("Disabled $removed_count SiteGround plugin(s) to prevent redirect loops");
        } else {
            $this->log('No SiteGround plugins found to disable');
        }
    }

    private function log($message) {
        $upload_dir = wp_upload_dir();
        $log_file = $upload_dir['basedir'] . '/custom-migrator/logs/import.log';
        $timestamp = date('Y-m-d H:i:s');
        error_log("[$timestamp] $message\n", 3, $log_file);
    }
}
