#!/usr/bin/env bash
#
# Install (or update) the Generic Bank Bot as a systemd service.
# One uvicorn process serves both the API and the built Vue frontend.
#
# Usage:
#   ./install-service.sh            # serve on port 8000
#   ./install-service.sh 80         # serve on port 80 (adds CAP_NET_BIND_SERVICE)
#
# Run as a normal user (NOT root) so the service runs as you; the script calls
# sudo only for the privileged steps.

set -euo pipefail

SERVICE_NAME="generic-bot"
PORT="${1:-8000}"

# --- Resolve project paths relative to this script -------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIST="$PROJECT_ROOT/frontend/dist"
VENV_PY="$BACKEND_DIR/.venv/bin/python"
VENV_UVICORN="$BACKEND_DIR/.venv/bin/uvicorn"

# Run the service as the invoking user (works even if the script is run via sudo).
RUN_USER="${SUDO_USER:-$(id -un)}"

echo "==> Project root : $PROJECT_ROOT"
echo "==> Backend dir  : $BACKEND_DIR"
echo "==> Run as user  : $RUN_USER"
echo "==> Port         : $PORT"

# --- Pre-flight checks -----------------------------------------------------
if [[ ! -d "$BACKEND_DIR/app" ]]; then
  echo "ERROR: $BACKEND_DIR/app not found. Run this script from inside the repo's deploy/ folder." >&2
  exit 1
fi

if [[ ! -x "$VENV_UVICORN" ]]; then
  echo "ERROR: $VENV_UVICORN not found." >&2
  echo "       Create the venv and install deps first:" >&2
  echo "         cd $BACKEND_DIR && python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

# Python must be >= 3.10 (the code uses 'str | None' syntax).
PYVER="$("$VENV_PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [[ "$(printf '%s\n' "3.10" "$PYVER" | sort -V | head -n1)" != "3.10" ]]; then
  echo "ERROR: venv Python is $PYVER, but >= 3.10 is required." >&2
  echo "       Recreate the venv with Python 3.12:" >&2
  echo "         cd $BACKEND_DIR && rm -rf .venv && python3.12 -m venv .venv \\" >&2
  echo "           && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi
echo "==> venv Python  : $PYVER (OK)"

if [[ ! -d "$FRONTEND_DIST" ]]; then
  echo "WARNING: $FRONTEND_DIST not found — the UI won't be served (API only)."
  echo "         Build it with: cd $PROJECT_ROOT/frontend && npm install && npm run build"
fi

# --- Port 80 needs the bind capability -------------------------------------
CAP_LINE=""
if [[ "$PORT" -lt 1024 ]]; then
  CAP_LINE="AmbientCapabilities=CAP_NET_BIND_SERVICE"
fi

# --- Write the unit file ---------------------------------------------------
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
echo "==> Writing $UNIT_PATH"
sudo tee "$UNIT_PATH" >/dev/null <<EOF
[Unit]
Description=UHBVN Assistant (FastAPI serving Vue build)
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=-$BACKEND_DIR/.env
ExecStart=$VENV_UVICORN app.main:app --host 0.0.0.0 --port $PORT
$CAP_LINE
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# --- Enable + (re)start ----------------------------------------------------
echo "==> Reloading systemd and starting the service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME" >/dev/null
sudo systemctl restart "$SERVICE_NAME"

# --- Open the firewall (firewalld), best effort ----------------------------
if command -v firewall-cmd >/dev/null 2>&1 && sudo firewall-cmd --state >/dev/null 2>&1; then
  echo "==> Opening port $PORT/tcp in firewalld"
  sudo firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null
  sudo firewall-cmd --reload >/dev/null
else
  echo "NOTE: firewalld not active — make sure port $PORT is reachable yourself."
fi

# --- Report ----------------------------------------------------------------
sleep 1
echo
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
if systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "SUCCESS: $SERVICE_NAME is running. Open: http://${IP:-SERVER_IP}:${PORT}"
  echo "It will stay up after you log out, and restart on boot."
else
  echo "The service is NOT active. Check logs with:"
  echo "  sudo journalctl -u $SERVICE_NAME -e --no-pager"
fi

case "$PROJECT_ROOT" in
  /home/*)
    echo
    echo "SELinux hint: your project is under /home, which SELinux may block for"
    echo "services. If status shows a permission error, run:"
    echo "  sudo restorecon -Rv \"$PROJECT_ROOT\""
    echo "  sudo ausearch -m avc -ts recent     # to see denials"
    ;;
esac
