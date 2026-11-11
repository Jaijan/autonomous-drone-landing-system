#!/usr/bin/env bash
set -euo pipefail
GCS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$GCS_DIR")"
if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
elif [ -x "$GCS_DIR/.venv/bin/python" ]; then
    PYTHON="$GCS_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi
cd "$GCS_DIR"
printf 'Starting Auto Drone GCS from %s on port 8000\n' "$GCS_DIR"
exec "$PYTHON" -m uvicorn launcher:app --app-dir "$GCS_DIR" --host 0.0.0.0 --port 8000
