FROM wordpress:latest

# Install WP-CLI and required tools
RUN apt-get update && apt-get install -y \
    less \
    wget \
    unzip \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Install WP-CLI
RUN curl -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar \
    && chmod +x wp-cli.phar \
    && mv wp-cli.phar /usr/local/bin/wp

# Download SQLite Integration plugin
RUN cd /tmp && \
    wget https://downloads.wordpress.org/plugin/sqlite-database-integration.2.1.13.zip && \
    unzip sqlite-database-integration.2.1.13.zip && \
    rm sqlite-database-integration.2.1.13.zip

# Copy custom migrator plugin
COPY plugin /tmp/custom-migrator

# Copy scripts
COPY wp-auto-install.sh /usr/local/bin/wp-auto-install.sh
COPY custom-entrypoint.sh /usr/local/bin/custom-entrypoint.sh

# Make scripts executable
RUN chmod +x /usr/local/bin/wp-auto-install.sh /usr/local/bin/custom-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/custom-entrypoint.sh"]
CMD ["apache2-foreground"]

EXPOSE 80
