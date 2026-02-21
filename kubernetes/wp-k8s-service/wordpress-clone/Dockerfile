FROM wordpress:6.4-apache

# Install MySQL client for health checks and wait logic
RUN apt-get update && \
    apt-get install -y default-mysql-client && \
    rm -rf /var/lib/apt/lists/*

# Pre-install custom-migrator plugin
COPY custom-migrator/ /var/www/html/wp-content/plugins/custom-migrator/

# Custom entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["apache2-foreground"]
