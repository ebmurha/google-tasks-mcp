FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BIND_HOST=0.0.0.0 \
    BIND_PORT=8787 \
    DB_PATH=/var/lib/google-tasks-mcp/google-tasks.db

WORKDIR /app

RUN addgroup --system google-tasks \
    && adduser --system --ingroup google-tasks --home /app google-tasks \
    && mkdir -p /var/lib/google-tasks-mcp \
    && chown -R google-tasks:google-tasks /app /var/lib/google-tasks-mcp

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir .

USER google-tasks

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import json, urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8787/healthz')) == {'ok': True}"

CMD ["python", "-m", "google_tasks_mcp", "--transport", "http"]
