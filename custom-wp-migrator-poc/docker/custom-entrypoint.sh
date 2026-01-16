#!/bin/bash
set -e

# Fix Apache MPM configuration before anything else
echo "Fixing Apache MPM configuration..."
rm -f /etc/apache2/mods-enabled/mpm_event.load \
      /etc/apache2/mods-enabled/mpm_event.conf \
      /etc/apache2/mods-enabled/mpm_worker.load \
      /etc/apache2/mods-enabled/mpm_worker.conf

# Ensure mpm_prefork is enabled
if [ ! -L /etc/apache2/mods-enabled/mpm_prefork.load ]; then
    ln -s /etc/apache2/mods-available/mpm_prefork.load /etc/apache2/mods-enabled/mpm_prefork.load
fi
if [ ! -L /etc/apache2/mods-enabled/mpm_prefork.conf ]; then
    ln -s /etc/apache2/mods-available/mpm_prefork.conf /etc/apache2/mods-enabled/mpm_prefork.conf
fi

echo "MPM configuration fixed. Only mpm_prefork is enabled."

# Call the original WordPress entrypoint
exec docker-entrypoint.sh "$@"
