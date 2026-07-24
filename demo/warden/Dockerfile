# syntax=docker/dockerfile:1
#
# Two build targets from one context (demo/warden/):
#   --target warden  -> the session manager + reverse proxy (app.py)
#   --target shim    -> the create-body authz shim (authz_shim.py)
# Both are Trusted Computing Base; both are cosign-signed + SBOM-attested in
# .github/workflows/demo-publish.yml (a follow-up). Base pinned by digest in
# deploy (this bare tag is replaced at build time).
FROM python:3.14-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
# Import as the `warden` namespace package so `from . import constants` resolves
# both here (uvicorn warden.app:app) and in the repo tests (demo.warden.app).
COPY constants.py app.py authz_shim.py /app/warden/
RUN useradd --uid 1001 --create-home warden
USER warden

FROM base AS warden
EXPOSE 8080
CMD ["uvicorn", "warden.app:app", "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "1", "--log-level", "warning"]

FROM base AS shim
EXPOSE 2375
CMD ["uvicorn", "warden.authz_shim:app", "--host", "0.0.0.0", "--port", "2375", \
     "--workers", "1", "--log-level", "warning"]
