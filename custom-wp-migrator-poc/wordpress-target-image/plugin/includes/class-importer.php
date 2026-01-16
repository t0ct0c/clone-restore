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
    
    public function import($archive_path = null, $archive_url = null) {
        try {
            $this->log('Starting import...');
            
            // Import check removed for automated provisioning POC
            // All target instances are ephemeral and designed to receive imports
            
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
            $this->import_database($extract_dir . '/database.sql');
            
            // Restore files
            $this->log('Restoring files...');
            $this->restore_files($extract_dir . '/wp-content');
            
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
    
    private function import_database($db_file) {
        global $wpdb;
        
        if (!file_exists($db_file)) {
            throw new Exception('Database file not found in archive');
        }
        
        $sql = file_get_contents($db_file);
        
        if (empty($sql)) {
            throw new Exception('Database file is empty');
        }
        
        // Check if we're on SQLite
        $is_sqlite = $this->is_sqlite_database();
        
        if ($is_sqlite) {
            // SQLite: Clear existing data but keep table structure
            $this->log('SQLite detected - clearing existing data...');
            $this->truncate_all_tables();
        } else {
            // MySQL: Drop and recreate tables
            $this->log('Dropping existing tables...');
            $this->drop_all_tables();
        }
        
        // Replace source URLs with target URLs
        $old_url = $this->extract_url_from_sql($sql);
        $new_url = get_site_url();
        
        if ($old_url && $old_url !== $new_url) {
            $this->log("Replacing URLs: $old_url -> $new_url");
            $sql = $this->replace_urls_in_sql($sql, $old_url, $new_url);
        }
        
        // Split into individual queries
        $queries = array_filter(
            array_map('trim', explode(";\n", $sql)),
            function($query) {
                return !empty($query) && strpos($query, '--') !== 0;
            }
        );
        
        // Execute queries
        foreach ($queries as $query) {
            // On SQLite, skip CREATE TABLE and DROP TABLE statements
            if ($is_sqlite) {
                $query_upper = strtoupper(trim($query));
                if (strpos($query_upper, 'CREATE TABLE') === 0 || 
                    strpos($query_upper, 'DROP TABLE') === 0 ||
                    strpos($query_upper, 'ALTER TABLE') === 0) {
                    continue;
                }
            }
            
            $result = $wpdb->query($query);
            
            if ($result === false && !empty($wpdb->last_error)) {
                $this->log('Query warning: ' . $wpdb->last_error);
            }
        }
    }
    
    private function is_sqlite_database() {
        // Check if SQLite database integration plugin is active
        if (defined('SQLITE_DB_DROPIN_VERSION')) {
            return true;
        }
        // Check for db.php dropin
        if (file_exists(WP_CONTENT_DIR . '/db.php')) {
            $db_content = file_get_contents(WP_CONTENT_DIR . '/db.php');
            if (strpos($db_content, 'sqlite') !== false) {
                return true;
            }
        }
        return false;
    }
    
    private function truncate_all_tables() {
        global $wpdb;
        
        // Get all WordPress tables
        $tables = $wpdb->get_col("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '{$wpdb->prefix}%'");
        
        foreach ($tables as $table) {
            $wpdb->query("DELETE FROM `$table`");
            $this->log("Cleared table: $table");
        }
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
    
    private function extract_url_from_sql($sql) {
        // Extract siteurl from wp_options table
        if (preg_match("/INSERT INTO [^`]*`wp_options`[^;]*'siteurl'[^']*'([^']+)'/", $sql, $matches)) {
            return $matches[1];
        }
        return null;
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
    
    private function restore_files($source_wp_content) {
        if (!file_exists($source_wp_content)) {
            throw new Exception('wp-content directory not found in archive');
        }
        
        $dest_wp_content = WP_CONTENT_DIR;
        $is_sqlite = $this->is_sqlite_database();
        
        // Plugins to preserve on SQLite targets (essential for operation)
        $preserve_plugins = array();
        if ($is_sqlite) {
            $preserve_plugins = array(
                'sqlite-database-integration',
                'custom-migrator'
            );
        }
        
        // Backup essential plugins before restore
        $plugin_backups = array();
        foreach ($preserve_plugins as $plugin) {
            $plugin_path = $dest_wp_content . '/plugins/' . $plugin;
            if (file_exists($plugin_path)) {
                $backup_path = sys_get_temp_dir() . '/wp_plugin_backup_' . $plugin . '_' . uniqid();
                $this->recursive_copy($plugin_path, $backup_path);
                $plugin_backups[$plugin] = $backup_path;
                $this->log("Backed up essential plugin: $plugin");
            }
        }
        
        // Also backup db.php dropin for SQLite
        $db_php_backup = null;
        if ($is_sqlite && file_exists($dest_wp_content . '/db.php')) {
            $db_php_backup = sys_get_temp_dir() . '/wp_db_php_backup_' . uniqid();
            copy($dest_wp_content . '/db.php', $db_php_backup);
            $this->log('Backed up db.php dropin');
        }
        
        // Restore specific directories
        $items_to_restore = array('themes', 'plugins', 'uploads');
        
        foreach ($items_to_restore as $item) {
            $src = $source_wp_content . '/' . $item;
            $dest = $dest_wp_content . '/' . $item;
            
            if (file_exists($src)) {
                // Remove existing and copy new
                if (file_exists($dest)) {
                    $this->recursive_delete($dest);
                }
                $this->recursive_copy($src, $dest);
            }
        }
        
        // Restore essential plugins
        foreach ($plugin_backups as $plugin => $backup_path) {
            $plugin_dest = $dest_wp_content . '/plugins/' . $plugin;
            $this->recursive_copy($backup_path, $plugin_dest);
            $this->recursive_delete($backup_path);
            $this->log("Restored essential plugin: $plugin");
        }
        
        // Restore db.php dropin
        if ($db_php_backup && file_exists($db_php_backup)) {
            copy($db_php_backup, $dest_wp_content . '/db.php');
            unlink($db_php_backup);
            $this->log('Restored db.php dropin');
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
    
    private function log($message) {
        $upload_dir = wp_upload_dir();
        $log_file = $upload_dir['basedir'] . '/custom-migrator/logs/import.log';
        $timestamp = date('Y-m-d H:i:s');
        error_log("[$timestamp] $message\n", 3, $log_file);
    }
}
