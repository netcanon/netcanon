# syntax=docker/dockerfile:1.7
#
# Netcanon — multi-vendor network config translator
# Multi-stage build: wheels assembled in builder; runtime is minimal.

# ===========================================================================
# Stage 1 — wheel builder
# ===========================================================================
FROM python:3.14-slim-bookworm AS builder

# build-essential lets cryptography / paramiko / pyyaml fall back to source
# if the wheel index lacks a Python 3.13 / linux/amd64 prebuilt.  The runtime
# stage doesn't carry these.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy project metadata + source.  README + LICENSE go in to satisfy
# pyproject.toml (readme = "README.md", license-files = ["LICENSE"]).
COPY pyproject.toml README.md LICENSE ./
COPY netcanon/ ./netcanon/

# Build the netcanon wheel + collect every dependency as a wheel into /wheels.
# Runtime stage installs from /wheels with --no-index to guarantee no
# network access during the runtime layer.
RUN pip install --no-cache-dir --upgrade pip wheel \
    && pip wheel --no-cache-dir --wheel-dir /wheels .


# ===========================================================================
# Stage 2 — runtime
# ===========================================================================
FROM python:3.14-slim-bookworm AS runtime

# curl is the only runtime addition — used by HEALTHCHECK.  No build tools.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r app --gid=1000 \
    && useradd -r -g app --uid=1000 \
        --create-home --home-dir=/home/app --shell=/bin/bash app

WORKDIR /app

# Install netcanon + dependencies from the prebuilt wheels.
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels netcanon \
    && rm -rf /wheels

# Per-vendor backup-side device definitions — read by the app's lifespan
# at startup (DefinitionLoader walks /app/definitions).  These ship in the
# image rather than being bind-mounted because they're tracked-content,
# not operator state.
COPY definitions/ /app/definitions/

# Operator state directories — bind-mount for persistence across container
# restarts.  Default to /app/configs (backup output) + /app/data (jobs /
# devices / schedules root, mirrors NETCANON_DATA_DIR semantics).
RUN mkdir -p /app/configs /app/data \
    && chown -R app:app /app /home/app

USER app

ENV NETCANON_CONFIGS_DIR=/app/configs \
    NETCANON_DATA_DIR=/app/data \
    NETCANON_HOST=0.0.0.0 \
    NETCANON_PORT=8000 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# HEALTHCHECK lets `docker run` / orchestrators see when the server is
# actually responsive vs just-bound-the-port.  Cheap probe at /health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Operator-overridable bind-mount targets.
VOLUME ["/app/configs", "/app/data"]

ENTRYPOINT ["uvicorn", "netcanon.main:app", "--host", "0.0.0.0", "--port", "8000"]

# OCI labels for image discovery + supply-chain provenance.  Repository
# label is what GHCR keys against for "View source" links on the package
# page.  GitHub Container Registry attaches additional labels via the
# metadata-action in the publish workflow (created / revision / etc).
LABEL org.opencontainers.image.title="Netcanon" \
      org.opencontainers.image.description="Multi-vendor network config translator with a verifiable cross-vendor audit" \
      org.opencontainers.image.source="https://github.com/netcanon/netcanon" \
      org.opencontainers.image.documentation="https://github.com/netcanon/netcanon/blob/main/README.md" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="Netcanon contributors"
