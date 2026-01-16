<?php

if (!defined('ABSPATH')) {
    exit;
}

class Custom_Migrator_Exporter {
    
    private static $instance = null;
    
    public static function get_instance() {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }
    
    public function export() {
        try {
            $this->log('Starting export...');
            
            // Create temp directory
            $temp_dir = $this->create_temp_dir();
            
            // Export database
            $this->log('Exporting database...');
            $db_file = $this->export_database($temp_dir);
            
            // Copy wp-content
            $this->log('Copying wp-content files...');
            $this->copy_wp_content($temp_dir);
            
            // Create archive
            $this->log('Creating archive...');
            $archive_path = $this->create_archive($temp_dir);
            
            // Cleanup temp directory
            $this->cleanup_temp_dir($temp_dir);
            
            $this->log('Export completed successfully.');
            
            return array(
                'success' => true,
                'archive_path' => $archive_path,
                'archive_name' => basename($archive_path),
                'size_bytes' => filesize($archive_path),
                'download_url' => $this->get_download_url(basename($archive_path))
            );
            
        } catch (Exception $e) {
            $this->log('Export failed: ' . $e->getMessage());
            return array(
                'success' => false,
                'error' => $e->getMessage()
            );
        }
    }
    
    private function export_database($temp_dir) {
        global $wpdb;
        
        $db_file = $temp_dir . '/database.sql';
        $handle = fopen($db_file, 'w');
        
        if (!$handle) {
            throw new Exception('Could not create database file');
        }
        
        // Get all tables
        $tables = $wpdb->get_results('SHOW TABLES', ARRAY_N);
        
        foreach ($tables as $table) {
            $table_name = $table[0];
            
            // Get CREATE TABLE statement
            $create_table = $wpdb->get_row("SHOW CREATE TABLE `$table_name`", ARRAY_N);
            fwrite($handle, "\n\n-- Table: $table_name\n");
            fwrite($handle, "DROP TABLE IF EXISTS `$table_name`;\n");
            fwrite($handle, $create_table[1] . ";\n\n");
            
            // Get table data
            $rows = $wpdb->get_results("SELECT * FROM `$table_name`", ARRAY_A);
            
            if (!empty($rows)) {
                foreach ($rows as $row) {
                    $columns = array_keys($row);
                    $values = array_values($row);
                    
                    $values = array_map(function($value) use ($wpdb) {
                        if ($value === null) {
                            return 'NULL';
                        }
                        return "'" . $wpdb->_real_escape($value) . "'";
                    }, $values);
                    
                    $insert = sprintf(
                        "INSERT INTO `%s` (`%s`) VALUES (%s);\n",
                        $table_name,
                        implode('`, `', $columns),
                        implode(', ', $values)
                    );
                    
                    fwrite($handle, $insert);
                }
            }
        }
        
        fclose($handle);
        return $db_file;
    }
    
    private function copy_wp_content($temp_dir) {
        $wp_content_src = WP_CONTENT_DIR;
        $wp_content_dest = $temp_dir . '/wp-content';
        
        if (!mkdir($wp_content_dest, 0755, true)) {
            throw new Exception('Could not create wp-content directory');
        }
        
        // Only copy essential items and skip large directories
        $items_to_copy = array('themes', 'plugins');
        
        foreach ($items_to_copy as $item) {
            $src = $wp_content_src . '/' . $item;
            $dest = $wp_content_dest . '/' . $item;
            
            if (file_exists($src)) {
                $this->log("Copying $item...");
                // Use system command for faster copying
                exec("cp -r " . escapeshellarg($src) . " " . escapeshellarg($dest));
            }
        }
        
        // Create uploads directory but don't copy files for POC
        mkdir($wp_content_dest . '/uploads', 0755, true);
        $this->log('Skipping uploads for POC');
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
    
    private function create_archive($temp_dir) {
        $upload_dir = wp_upload_dir();
        $exports_dir = $upload_dir['basedir'] . '/custom-migrator/exports';
        
        if (!file_exists($exports_dir)) {
            wp_mkdir_p($exports_dir);
        }
        
        $archive_name = 'migration-' . date('YmdHis') . '.zip';
        $archive_path = $exports_dir . '/' . $archive_name;
        
        $zip = new ZipArchive();
        if ($zip->open($archive_path, ZipArchive::CREATE) !== true) {
            throw new Exception('Could not create zip archive');
        }
        
        $this->add_dir_to_zip($zip, $temp_dir, '');
        $zip->close();
        
        return $archive_path;
    }
    
    private function add_dir_to_zip($zip, $path, $relative_path) {
        $items = scandir($path);
        
        foreach ($items as $item) {
            if ($item === '.' || $item === '..') {
                continue;
            }
            
            $full_path = $path . '/' . $item;
            $zip_path = $relative_path ? $relative_path . '/' . $item : $item;
            
            if (is_dir($full_path)) {
                $zip->addEmptyDir($zip_path);
                $this->add_dir_to_zip($zip, $full_path, $zip_path);
            } else {
                $zip->addFile($full_path, $zip_path);
            }
        }
    }
    
    private function create_temp_dir() {
        $upload_dir = wp_upload_dir();
        $base_tmp = $upload_dir['basedir'] . '/custom-migrator/tmp';
        $temp_dir = $base_tmp . '/export-' . uniqid();
        
        if (!wp_mkdir_p($temp_dir)) {
            throw new Exception('Could not create temporary directory');
        }
        
        return $temp_dir;
    }
    
    private function cleanup_temp_dir($temp_dir) {
        $this->recursive_delete($temp_dir);
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
    
    private function get_download_url($archive_name) {
        $upload_dir = wp_upload_dir();
        return $upload_dir['baseurl'] . '/custom-migrator/exports/' . $archive_name;
    }
    
    private function log($message) {
        $upload_dir = wp_upload_dir();
        $log_file = $upload_dir['basedir'] . '/custom-migrator/logs/export.log';
        $timestamp = date('Y-m-d H:i:s');
        error_log("[$timestamp] $message\n", 3, $log_file);
    }
}
