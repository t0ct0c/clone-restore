#!/bin/bash
set -e

# Fix Apache MPM configuration
echo "Fixing Apache MPM configuration..."
a2dismod mpm_event mpm_worker 2>/dev/null || true
a2enmod mpm_prefork 2>/dev/null || true
echo "MPM configuration fixed."

# Start WordPress initialization in background
(/usr/local/bin/wp-auto-install.sh > /var/log/wp-init.log 2>&1 &)

# Run original WordPress entrypoint
exec docker-entrypoint.sh "$@"
