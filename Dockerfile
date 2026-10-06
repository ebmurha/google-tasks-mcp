FROM litestream/litestream:0.5.8 AS litestream

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BIND_HOST=0.0.0.0 \
    DB_PATH=/var/lib/google-tasks-mcp/google-tasks.db

WORKDIR /app

RUN addgroup --system google-tasks \
    && adduser --system --ingroup google-tasks --home /app google-tasks \
    && addgroup --system --gid 1000 runtime-secrets \
    && adduser google-tasks runtime-secrets \
    && mkdir -p /var/lib/google-tasks-mcp \
    && chown -R google-tasks:google-tasks /app /var/lib/google-tasks-mcp

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
COPY deploy/litestream.yml /etc/litestream.yml
COPY deploy/container-entrypoint.sh /usr/local/bin/google-tasks-mcp-entrypoint
COPY --from=litestream /usr/local/bin/litestream /usr/local/bin/litestream

RUN pip install --no-cache-dir . \
    && chmod 755 /usr/local/bin/google-tasks-mcp-entrypoint

USER google-tasks

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import json, os, urllib.request; port=os.getenv('BIND_PORT') or os.getenv('PORT', '8787'); assert json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz')) == {'ok': True}"

ENTRYPOINT ["google-tasks-mcp-entrypoint"]
