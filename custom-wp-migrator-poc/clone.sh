#!/bin/bash

# Clone WordPress site from source to target using Custom Migrator API

set -e

# Configuration
SOURCE_URL="${SOURCE_URL:-http://localhost:8080}"
TARGET_URL="${TARGET_URL:-http://localhost:8081}"
SOURCE_API_KEY="${SOURCE_API_KEY}"
TARGET_API_KEY="${TARGET_API_KEY}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check required variables
if [ -z "$SOURCE_API_KEY" ] || [ -z "$TARGET_API_KEY" ]; then
    log_error "SOURCE_API_KEY and TARGET_API_KEY environment variables must be set"
    echo ""
    echo "Usage:"
    echo "  SOURCE_API_KEY=xxx TARGET_API_KEY=yyy ./clone.sh"
    echo ""
    echo "Get API keys from:"
    echo "  Source: $SOURCE_URL/wp-admin/options-general.php?page=custom-migrator-settings"
    echo "  Target: $TARGET_URL/wp-admin/options-general.php?page=custom-migrator-settings"
    exit 1
fi

log_info "Starting clone process..."
log_info "Source: $SOURCE_URL"
log_info "Target: $TARGET_URL"

# Step 1: Export from source
log_info "Step 1: Exporting from source..."
EXPORT_RESPONSE=$(curl -s -X POST \
    -H "X-Migrator-Key: $SOURCE_API_KEY" \
    "$SOURCE_URL/wp-json/custom-migrator/v1/export")

# Check for errors
if echo "$EXPORT_RESPONSE" | grep -q '"success":false\|"code":"'; then
    log_error "Export failed:"
    echo "$EXPORT_RESPONSE" | jq '.'
    exit 1
fi

ARCHIVE_URL=$(echo "$EXPORT_RESPONSE" | jq -r '.download_url')
ARCHIVE_SIZE=$(echo "$EXPORT_RESPONSE" | jq -r '.size_bytes')

# Convert localhost source URL to Docker network hostname only if both are local containers
if [[ "$SOURCE_URL" == "http://localhost:8080" ]] && [[ "$TARGET_URL" == "http://localhost:8081" ]]; then
    ARCHIVE_URL=$(echo "$ARCHIVE_URL" | sed 's|http://localhost:8080|http://wp_source|g')
    log_info "(Using Docker network hostname for local containers)"
fi

log_info "Export completed successfully"
log_info "Archive URL: $ARCHIVE_URL"
log_info "Archive size: $(numfmt --to=iec-i --suffix=B $ARCHIVE_SIZE 2>/dev/null || echo "$ARCHIVE_SIZE bytes")"

# Step 2: Import to target
log_info "Step 2: Importing to target..."
IMPORT_RESPONSE=$(curl -s -X POST \
    -H "X-Migrator-Key: $TARGET_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"archive_url\": \"$ARCHIVE_URL\"}" \
    "$TARGET_URL/wp-json/custom-migrator/v1/import")

# Check for errors
if echo "$IMPORT_RESPONSE" | grep -q '"success":false\|"code":"'; then
    log_error "Import failed:"
    echo "$IMPORT_RESPONSE" | jq '.'
    exit 1
fi

log_info "Import completed successfully"
echo ""
log_info "✓ Clone completed!"
log_info "Target site is now a copy of the source site"
echo ""
log_warning "IMPORTANT: You may need to update site URLs and permalinks in the target site"
log_info "Visit: $TARGET_URL/wp-admin/"
