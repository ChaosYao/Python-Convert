# Multi-stage build for Python-Convert Sidecar
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY requirements.txt pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install runtime dependencies (if needed for python-ndn)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create directories
RUN mkdir -p /app /root/.ndn

# Copy Python dependencies from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY src/ ./src/
COPY config.yaml ./
COPY pyproject.toml ./

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Install the package in development mode
RUN pip install --no-cache-dir -e .

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NDN_PIB_PATH=/root/.ndn/pib.db \
    NDN_TPM_PATH=/root/.ndn/ndnsec-key-file \
    MODE=sidecar \
    GRPC_SERVER_PORT=19090 \
    LOG_LEVEL=INFO

# Expose ports
EXPOSE 19090  
EXPOSE 6363   

# Run as root user to avoid permission issues with mounted volumes
# This is necessary because the mounted /root/.ndn directory needs root access
USER root

# Set entrypoint (simple pass-through since we're running as root)
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Health check (simple port check)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import socket; s = socket.socket(); s.settimeout(5); result = s.connect_ex(('localhost', 19090)); s.close(); exit(0 if result == 0 else 1)" || exit 1

# Default command: run sidecar mode
CMD ["python", "-m", "python_project", "sidecar"]

