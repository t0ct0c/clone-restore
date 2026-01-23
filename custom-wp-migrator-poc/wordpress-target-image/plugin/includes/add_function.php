<?php
$content = file_get_contents('class-importer.php');

// Find where to insert the new function (before extract_url_from_sql)
$insert_marker = '    private function extract_url_from_sql($sql, $prefix = \'wp_\') {';
$insert_pos = strpos($content, $insert_marker);

if ($insert_pos === false) {
    echo "ERROR: Could not find insertion point\n";
    exit(1);
}

// The new function to insert
$new_function = '    private function set_url_constants_in_config($target_url) {
        $config_file = ABSPATH . \'wp-config.php\';
        if (!file_exists($config_file)) {
            $this->log("Warning: wp-config.php not found");
            return;
        }

        $content = file_get_contents($config_file);
        $this->log("Setting WP_HOME and WP_SITEURL to: $target_url");
        
        // First, remove any existing WP_HOME/WP_SITEURL definitions
        $patterns = array(
            "/define\\\\s*\\\\(\\\\s*[\'\\"]WP_HOME[\'\\"]\\\\s*,\\\\s*[^;]+\\\\s*\\\\)\\\\s*;[\\\\r\\\\n]*/",
            "/define\\\\s*\\\\(\\\\s*[\'\\"]WP_SITEURL[\'\\"]\\\\s*,\\\\s*[^;]+\\\\s*\\\\)\\\\s*;[\\\\r\\\\n]*/"
        );
        
        foreach ($patterns as $pattern) {
            $content = preg_replace($pattern, \'\', $content);
        }
        
        // Find the line with require_once wp-settings.php
        $wp_settings_pattern = "/(\\\\\/\\\\*\\\\*[^*]*\\\\*+(?:[^*\\\\\/][^*]*\\\\*+)*\\\\\/[\\\\r\\\\n]+)?require_once\\\\s+.*wp-settings\\\\.php.*;\\\\s*$/m";
        
        if (preg_match($wp_settings_pattern, $content, $matches, PREG_OFFSET_CAPTURE)) {
            $insert_position = $matches[0][1];
            
            // Build the constants to insert
            $constants = "\\n/* URL constants set by migrator - DO NOT REMOVE */\\n";
            $constants .= "define(\'WP_HOME\', \'" . addslashes($target_url) . "\');\\n";
            $constants .= "define(\'WP_SITEURL\', \'" . addslashes($target_url) . "\');\\n";
            $constants .= "/* End migrator constants */\\n\\n";
            
            // Insert before wp-settings.php
            $content = substr_replace($content, $constants, $insert_position, 0);
            
            $result = file_put_contents($config_file, $content);
            if ($result !== false) {
                $this->log("Successfully set URL constants in wp-config.php before wp-settings.php");
            } else {
                $this->log("ERROR: Failed to write wp-config.php");
            }
        } else {
            $this->log("ERROR: Could not find wp-settings.php require line in wp-config.php");
        }
    }

';

// Insert the new function
$new_content = substr($content, 0, $insert_pos) . $new_function . substr($content, $insert_pos);

// Write the modified content
file_put_contents('class-importer.php', $new_content);

echo "SUCCESS: Added set_url_constants_in_config() function\n";
