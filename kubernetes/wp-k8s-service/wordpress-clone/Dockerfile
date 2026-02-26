FROM wordpress:6.9-apache

# Install MySQL client, WP-CLI, and required tools
RUN apt-get update && \
    apt-get install -y default-mysql-client curl unzip && \
    curl -o /usr/local/bin/wp https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar && \
    chmod +x /usr/local/bin/wp && \
    rm -rf /var/lib/apt/lists/*

# Custom entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Copy custom migrator plugin
COPY custom-migrator.zip /plugin.zip

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["apache2-foreground"]
