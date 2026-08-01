# syntax=docker/dockerfile:1.7
#
# Netcanon — multi-vendor network config translator
# Multi-stage build: wheels assembled in builder; runtime is minimal.

# ===========================================================================
# Stage 1 — wheel builder
# ===========================================================================
# Base image pinned by digest (the multi-arch index for 3.14.6-slim-bookworm)
# so the build is reproducible and not silently re-tagged upstream.  Dependabot's
# docker ecosystem bumps both the tag and this digest together.
FROM python:3.14.6-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30 AS builder

# build-essential lets cryptography / paramiko / pyyaml fall back to source
# if the wheel index lacks a Python 3.14 / linux/amd64 prebuilt.  The runtime
# stage doesn't carry these.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Version is derived from the git tag at build time via setuptools_scm.
# `.git/` is excluded from the Docker context (see .dockerignore), so
# setuptools_scm can't read tags directly here — instead the publishing
# workflow passes the resolved version as a build-arg, which becomes
# the SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NETCANON env var.  setuptools_scm
# checks for that env var first before trying git.  Local docker builds
# without CI either set the build-arg manually or fall back to the
# fallback_version configured in pyproject.toml.
ARG SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NETCANON=""
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NETCANON=$SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NETCANON

# Copy project metadata + source.  README + LICENSE go in to satisfy
# pyproject.toml (readme = "README.md", license-files = ["LICENSE"]).
# requirements.lock is the hash-pinned dependency manifest (audit e5b77d7 #5).
COPY pyproject.toml README.md LICENSE requirements.lock ./
COPY netcanon/ ./netcanon/

# Build every dependency wheel from the hash-pinned lock FIRST, then the
# netcanon wheel with --no-deps (audit e5b77d7 #5: "no pinned/hash-locked
# dependency manifest for shipped artifacts").  ``--require-hashes`` constrains
# the image's dependency input set to the exact versions in requirements.lock
# and verifies each artifact's hash, instead of re-resolving pyproject's ranges
# against whatever PyPI serves at build time.  requirements.lock is generated
# in THIS digest-pinned base image (tools/gen_requirements_lock.sh), so its
# wheels match the platform here; the runtime stage then installs from /wheels
# with --no-index, so only this locked set can ever be installed.
RUN pip install --no-cache-dir --upgrade pip wheel \
    && pip wheel --no-cache-dir --require-hashes -r requirements.lock --wheel-dir /wheels \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .


# ===========================================================================
# Stage 2 — runtime
# ===========================================================================
# Same digest-pinned base as the builder stage (see note above).
FROM python:3.14.6-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30 AS runtime

# curl is the only runtime addition — used by HEALTHCHECK.  No build tools.
# ``apt-get upgrade`` applies Debian security point-releases on top of the
# digest-pinned base (run3): the base tag is rebuilt less often than the
# point-releases land, so it can ship a stale package (e.g. libgnutls30
# behind a fixed CRITICAL CVE).  The gating Trivy scan in ci.yml fails the
# PR on exactly that, so patch it here at build time — the digest still
# pins the base layer; this is an explicit, auditable hardening layer.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
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

# Per-vendor backup-side device definitions are read by the app's lifespan
# at startup.  They now ship *inside the wheel* as package data
# (netcanon/definitions/library/, installed above), and the default
# `definitions_dir` resolves to that packaged copy — so there is no separate
# COPY here and no working-directory assumption.  Operators who maintain a
# custom definition tree mount it and point NETCANON_DEFINITIONS_DIR at it.

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

# SEC-01: `netcanon serve` reads host/port/auth from NETCANON_* env
# (default 0.0.0.0:8000) and refuses an unauthenticated non-loopback
# bind unless NETCANON_API_KEY or NETCANON_ALLOW_INSECURE_BIND is set.
ENTRYPOINT ["netcanon", "serve"]

# OCI labels for image discovery + supply-chain provenance.  Repository
# label is what GHCR keys against for "View source" links on the package
# page.  GitHub Container Registry attaches additional labels via the
# metadata-action in the publish workflow (created / revision / etc).
LABEL org.opencontainers.image.title="Netcanon" \
      org.opencontainers.image.description="Multi-vendor network config translator with a verifiable cross-vendor audit" \
      org.opencontainers.image.source="https://github.com/netcanon/netcanon" \
      org.opencontainers.image.documentation="https://github.com/netcanon/netcanon/blob/main/README.md" \
      org.opencontainers.image.url="https://demo.netcanon.net" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="Netcanon contributors"
