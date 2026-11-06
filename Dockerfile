# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.10.9 AS uv

FROM node:22-bookworm-slim AS frontend
WORKDIR /build/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
# De UI importeert deze gedeelde catalogus op hetzelfde relatieve bronpad.
COPY src/betonning/api_errors.json /build/src/betonning/api_errors.json
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY docs/hegemone/README.md ./README.md
COPY LICENSE ./LICENSE
COPY docs/hegemone/SECURITY.md ./SECURITY.md
COPY docs/hegemone/NATIVE_DEPLOYMENT.md ./NATIVE_DEPLOYMENT.md
COPY docs/hegemone/PUBLIC_BOUNDARY.md ./PUBLIC_BOUNDARY.md
COPY docs/hegemone/THIRD_PARTY.md docs/hegemone/FRONTEND_LICENSES.txt ./
COPY docs/hegemone/screenshots/ ./screenshots/
# Alleen de gelockte runtimeafhankelijkheden; de private packagebeschrijving
# en repositorydocumentatie worden niet als distributiemetadata geïnstalleerd.
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv uv export --locked --no-dev --extra mcp --no-emit-project --output-file /tmp/requirements.txt \
    && uv pip install --system --require-hashes -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt /app/pyproject.toml /app/uv.lock
COPY docs/hegemone/CONTRIBUTING.md docs/hegemone/SUPPORT.md docs/hegemone/CHANGELOG.md docs/hegemone/AGENT_SETUP.md docs/hegemone/AGENTS.md ./
COPY src/betonning/ ./src/betonning/
COPY --from=frontend /build/src/betonning/static/ ./src/betonning/static/
RUN groupadd --gid 10001 hegemone \
    && useradd --uid 10001 --gid hegemone --no-create-home hegemone \
    && mkdir /data && chown hegemone:hegemone /data
ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HEGEMONE_DB=/data/hegemone.db \
    HEGEMONE_ATTACHMENTS_DIR=/data/attachments \
    BETONNING_BASE_URL=http://127.0.0.1:8000
USER hegemone
# Controleer de verpakte modules/catalogi zonder data of netwerk te gebruiken.
RUN python -c "import betonning.server"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["sh", "-c", "umask 027 && exec uvicorn betonning.server:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 5"]
