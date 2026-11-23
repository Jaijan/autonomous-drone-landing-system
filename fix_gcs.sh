#!/usr/bin/env bash
# Repair old launcher copies that still embed the former Pi address.
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
LAUNCHER="$PROJECT_DIR/drone-gcs/launcher.py"
if [[ ! -f "$LAUNCHER" ]]; then
    echo "Missing $LAUNCHER. Place this script in the project root." >&2
    exit 1
fi

if [[ -n "${GCS_HOST:-}" ]]; then
    PI_IP="$GCS_HOST"
else
    PI_IP="$(hostname -I | awk '{print $1}')"
fi
if [[ ! "$PI_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "No IPv4 address found. Connect the Pi to your network, or run GCS_HOST=<PI_IP> bash fix_gcs.sh." >&2
    exit 1
fi

if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
elif [[ -x "$PROJECT_DIR/drone-gcs/.venv/bin/python" ]]; then
    PYTHON="$PROJECT_DIR/drone-gcs/.venv/bin/python"
else
    PYTHON="python3"
fi

# Do not rewrite the launcher while an existing GCS still owns this port.
"$PYTHON" - <<'PY'
import socket
import sys
with socket.socket() as sock:
    try:
        sock.bind(('0.0.0.0', 8000))
    except OSError:
        sys.exit('Port 8000 is in use. Stop the old GCS with Ctrl+C, then run this script again.')
PY

if grep -q '192\.168\.0\.2' "$LAUNCHER"; then
    BACKUP="$LAUNCHER.bak.$(date +%Y%m%d-%H%M%S)"
    cp -p -- "$LAUNCHER" "$BACKUP"
    sed -i "s/192\.168\.0\.2/$PI_IP/g" "$LAUNCHER"
    echo "Replaced the old IP. Backup: $BACKUP"
fi
export GCS_HOST="$PI_IP"
echo "Starting GCS from $PROJECT_DIR"
echo "Pi browser:     http://localhost:8000"
echo "Laptop browser: http://$PI_IP:8000"
echo "Keep this terminal open. Press Ctrl+C to stop."
exec "$PYTHON" -m uvicorn launcher:app --app-dir "$PROJECT_DIR/drone-gcs" --host 0.0.0.0 --port 8000
