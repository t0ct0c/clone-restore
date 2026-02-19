# WordPress K8s Service Dockerfile
# FastAPI service for Kubernetes-native WordPress clone/restore operations

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for Playwright, Camoufox, and other tools
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    libu2f-udev \
    libvulkan1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium)
# Note: We skip install-deps since we already installed system dependencies above
RUN playwright install chromium

# Copy application code
COPY app/ /app/app/

# Create directory for plugin
RUN mkdir -p /app/plugins

# Copy WordPress plugin
COPY plugins/custom-migrator.zip /app/plugin.zip

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PLUGIN_ZIP_PATH=/app/plugin.zip
ENV TIMEOUT=600

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
