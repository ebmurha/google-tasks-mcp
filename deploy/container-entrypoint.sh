#!/bin/sh
set -eu

if [ -n "${LITESTREAM_BUCKET:-}" ]; then
    : "${LITESTREAM_DB_PATH:?LITESTREAM_DB_PATH is required}"
    : "${LITESTREAM_ENDPOINT:?LITESTREAM_ENDPOINT is required}"
    : "${LITESTREAM_ACCESS_KEY_ID:?LITESTREAM_ACCESS_KEY_ID is required}"
    : "${LITESTREAM_SECRET_ACCESS_KEY:?LITESTREAM_SECRET_ACCESS_KEY is required}"
    export LITESTREAM_PATH="${LITESTREAM_PATH:-google-tasks-mcp/sqlite}"
    exec litestream replicate \
        -config /etc/litestream.yml \
        -restore-if-db-not-exists \
        -exec "python -m google_tasks_mcp --transport http"
fi

exec python -m google_tasks_mcp --transport http
