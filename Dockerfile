# Infrastructure Atlas - Production Dockerfile
# Compatible with Docker and Podman
#
# Build: docker build -t atlas:latest .
# Run:   docker run -d -p 8000:8000 --env-file .env atlas:latest

FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock* ./

# Install dependencies (without dev dependencies)
# Use CPU-only PyTorch to reduce image size (no CUDA libraries)
ENV UV_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Install the project itself
RUN uv sync --frozen --no-dev

# ─────────────────────────────────────────────────────────────────────────────
# Production image
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 atlas

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY --from=builder /app/src ./src
COPY --from=builder /app/alembic ./alembic
COPY --from=builder /app/alembic.ini ./

# Create data directory for caches/exports
RUN mkdir -p /app/data /app/logs && chown -R atlas:atlas /app

# Switch to non-root user
USER atlas

# Set environment
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Performance optimizations
    ATLAS_SKIP_DB_HEALTH_CHECK=1 \
    ATLAS_LAZY_AI_IMPORTS=1 \
    # Default storage backend
    ATLAS_STORAGE_BACKEND=mongodb

# Expose API port
EXPOSE 8000

# Health check - check if server responds (200 or 401 both indicate server is running)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -so /dev/null -w '%{http_code}' http://localhost:8000/api/health | grep -qE '^(200|401)$'

# Default command - production server with 4 workers
CMD ["uvicorn", "infrastructure_atlas.api.app:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4"]
