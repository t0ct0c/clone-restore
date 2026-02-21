#!/bin/bash
set -e

# Wait for MySQL sidecar to be ready
echo "Waiting for MySQL sidecar..."
while ! mysqladmin ping -h"127.0.0.1" --silent; do
    sleep 1
done
echo "MySQL is ready"

# If warm pool mode, skip WordPress setup
if [[ "$WARM_POOL_MODE" == "true" ]]; then
    echo "Warm pool mode - MySQL ready, skipping WordPress initialization"
    # Just start Apache, WordPress will be configured later
    exec docker-entrypoint.sh apache2-foreground
else
    # Normal clone pod - proceed with WordPress setup
    echo "Normal clone mode - proceeding with WordPress setup"
    exec docker-entrypoint.sh apache2-foreground
fi
