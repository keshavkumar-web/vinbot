#!/usr/bin/env bash
#
# UHBVN chatbot deployment — two-server topology.
#
#   Server 51 (backend): FastAPI+uvicorn via systemd, serves UI + /api on :8000
#   Server 103 (nginx) : public reverse proxy for https://uhbvn.vinbox.in -> 51:8000
#
# Usage:
#   On 51 :  export BACKEND_IP=10.x.x.x ; bash deploy.sh backend
#   On 103:  export BACKEND_IP=10.x.x.x ; bash deploy.sh nginx          # HTTP only
#            export BACKEND_IP=10.x.x.x RUN_CERTBOT=true ; bash deploy.sh nginx   # +HTTPS
#
# Idempotent: re-running updates code/config and restarts cleanly.
set -euo pipefail

# ---- config (override via environment) -------------------------------------
BACKEND_IP="${BACKEND_IP:-}"                       # 51's LAN IP that 103 can reach
DOMAIN="${DOMAIN:-uhbvn.vinbox.in}"
PORT="${PORT:-8000}"
APP_DIR="${APP_DIR:-/opt/uhbvn}"
SERVICE_USER="${SERVICE_USER:-uhbvn}"
SRC_TARBALL="${SRC_TARBALL:-$HOME/Chatbot/uhbvn.tar.gz}"
RUN_CERTBOT="${RUN_CERTBOT:-false}"                # nginx role only
EMAIL="${EMAIL:-repository@vinbox.in}"             # for Let's Encrypt
# ---------------------------------------------------------------------------

log()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m    %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

ROLE="${1:-}"
[ -n "$BACKEND_IP" ] || die "Set BACKEND_IP first, e.g.  export BACKEND_IP=10.0.0.51"

deploy_backend() {
  [ -f "$SRC_TARBALL" ] || die "Tarball not found: $SRC_TARBALL (set SRC_TARBALL=...)"

  log "1/7 Unpacking app to $APP_DIR"
  sudo mkdir -p "$APP_DIR"
  sudo tar -xzf "$SRC_TARBALL" -C "$APP_DIR"

  log "2/7 Ensuring service user '$SERVICE_USER'"
  id "$SERVICE_USER" >/dev/null 2>&1 || \
    sudo adduser --system --group --home "$APP_DIR" "$SERVICE_USER"
  sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

  log "3/7 Python venv + dependencies"
  [ -d "$APP_DIR/backend/.venv" ] || \
    sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/backend/.venv"
  sudo -u "$SERVICE_USER" "$APP_DIR/backend/.venv/bin/pip" install -q -U pip
  sudo -u "$SERVICE_USER" "$APP_DIR/backend/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

  log "4/7 Secrets (.env)"
  if [ -f "$APP_DIR/backend/.env" ]; then
    warn ".env already exists — leaving it unchanged."
  else
    read -rsp "    Enter OPENAI_API_KEY: " OPENAI_KEY; echo
    [ -n "$OPENAI_KEY" ] || die "Empty OPENAI_API_KEY"
    sudo -u "$SERVICE_USER" tee "$APP_DIR/backend/.env" >/dev/null <<EOF
OPENAI_API_KEY=$OPENAI_KEY
ALLOWED_ORIGINS=https://$DOMAIN
EOF
    sudo chmod 600 "$APP_DIR/backend/.env"
  fi

  log "5/7 Building frontend"
  if ! command -v node >/dev/null 2>&1 || \
       [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 18 ]; then
    warn "Installing Node 20"
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
  fi
  sudo -u "$SERVICE_USER" bash -c "cd '$APP_DIR/frontend' && npm ci && npm run build"
  [ -f "$APP_DIR/frontend/dist/index.html" ] || die "Frontend build produced no dist/index.html"

  log "6/7 systemd service (binds $BACKEND_IP:$PORT, single worker)"
  sudo tee /etc/systemd/system/uhbvn.service >/dev/null <<EOF
[Unit]
Description=UHBVN Assistant API
After=network.target

[Service]
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$APP_DIR/backend/.env
ExecStart=$APP_DIR/backend/.venv/bin/uvicorn app.main:app --host $BACKEND_IP --port $PORT --workers 1 --timeout-keep-alive 75
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable uhbvn >/dev/null 2>&1 || true
  sudo systemctl restart uhbvn

  log "7/7 Health check"
  sleep 3
  if curl -fsS "http://$BACKEND_IP:$PORT/api/health"; then
    echo; log "Backend OK on http://$BACKEND_IP:$PORT"
    warn "Lock port $PORT to 103 only (cloud security group preferred on a k8s node)."
  else
    die "Health check failed — inspect: sudo journalctl -u uhbvn -n 50 --no-pager"
  fi
}

deploy_nginx() {
  command -v nginx >/dev/null 2>&1 || die "nginx is not installed on this host"

  log "1/3 Reachability: $DOMAIN backend at $BACKEND_IP:$PORT"
  curl -fsS "http://$BACKEND_IP:$PORT/api/health" >/dev/null \
    || die "Cannot reach backend $BACKEND_IP:$PORT from here (firewall / wrong IP / backend down)"

  log "2/3 Writing nginx site (additive; does not touch other vhosts)"
  sudo tee /etc/nginx/sites-available/uhbvn >/dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://$BACKEND_IP:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # SSE / token streaming
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }

    client_max_body_size 5m;
}
EOF
  sudo ln -sf /etc/nginx/sites-available/uhbvn /etc/nginx/sites-enabled/uhbvn
  sudo nginx -t
  sudo systemctl reload nginx

  if [ "$RUN_CERTBOT" = "true" ]; then
    log "3/3 HTTPS via certbot (requires DNS $DOMAIN -> this server)"
    command -v certbot >/dev/null 2>&1 || { sudo apt-get update; sudo apt-get install -y certbot python3-certbot-nginx; }
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
    sudo certbot renew --dry-run
    log "Live: https://$DOMAIN"
  else
    log "3/3 HTTP ready: http://$DOMAIN"
    warn "Re-run with RUN_CERTBOT=true to enable HTTPS (set DNS first)."
  fi
}

case "$ROLE" in
  backend) deploy_backend ;;
  nginx)   deploy_nginx ;;
  *) die "Usage: BACKEND_IP=<51-LAN-IP> bash deploy.sh <backend|nginx>" ;;
esac
