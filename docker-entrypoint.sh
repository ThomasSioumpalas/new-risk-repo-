#!/usr/bin/env bash
# Entrypoint for the Sextant container.
#
# When the container is started to serve the API (the default CMD, or any
# invocation whose first argument is "uvicorn"), apply database migrations
# before the server starts accepting traffic. Any other command (e.g. the
# `sextant` CLI, or a shell for debugging) runs as-is, unchanged.
set -euo pipefail

if [ "${1:-}" = "uvicorn" ]; then
    echo "Applying database migrations (alembic upgrade head)..." >&2
    alembic upgrade head
fi

exec "$@"
