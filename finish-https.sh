#!/bin/bash
# One-shot HTTPS cutover for the Meta Ad Agent.
# Run AFTER: (1) VCN ingress rule for TCP 80+443 is added, (2) a DuckDNS
# subdomain points at this VM's IP (82.70.42.188).
#   Usage:  bash ~/finish-https.sh <yourname>.duckdns.org
set -euo pipefail

DOMAIN="${1:?Usage: finish-https.sh <subdomain.duckdns.org>}"
APP_DIR=/home/opc/meta-ad-agent
HASH="$(cat /home/opc/caddy/pw.hash)"

echo "==> 1/6 Writing Caddyfile for ${DOMAIN}"
sudo mkdir -p /etc/caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
${DOMAIN} {
    encode gzip
    basic_auth {
        admin ${HASH}
    }
    reverse_proxy 127.0.0.1:8000
}
EOF

echo "==> 2/6 Switching app to internal 127.0.0.1:8000 (behind Caddy)"
sudo tee /etc/systemd/system/meta-ad-agent.service >/dev/null <<EOF
[Unit]
Description=Meta Ad Agent (FastAPI + scheduler)
After=network.target

[Service]
Type=simple
User=opc
WorkingDirectory=${APP_DIR}
Environment=HOME=/home/opc
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3.11 -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "==> 3/6 Installing Caddy systemd service"
sudo tee /etc/systemd/system/caddy.service >/dev/null <<EOF
[Unit]
Description=Caddy reverse proxy (auto-HTTPS)
After=network.target

[Service]
User=opc
Group=opc
Environment=HOME=/home/opc
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile
Restart=on-failure
RestartSec=5
AmbientCapabilities=CAP_NET_BIND_SERVICE
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
EOF

# Point CORS at the domain (same-origin, but explicit is safe).
if ! grep -q "^FUNNEL_ALLOWED_ORIGINS=" "${APP_DIR}/.env"; then
  echo "FUNNEL_ALLOWED_ORIGINS=https://${DOMAIN}" >> "${APP_DIR}/.env"
fi

echo "==> 4/6 Reloading + starting services"
sudo systemctl daemon-reload
sudo systemctl restart meta-ad-agent
sudo systemctl enable --now caddy
sudo systemctl restart caddy

echo "==> 5/6 Registering Telegram webhook (Approve/Reject buttons)"
TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' ${APP_DIR}/.env | cut -d= -f2-)"
SECRET="$(grep -E '^TELEGRAM_COMMAND_SECRET=' ${APP_DIR}/.env | cut -d= -f2-)"
sleep 8
curl -s "https://api.telegram.org/bot${TOKEN}/setWebhook?url=https://${DOMAIN}/api/telegram/command&secret_token=${SECRET}" ; echo ""

echo "==> 6/6 Verifying"
echo "  internal app: $(curl -s http://127.0.0.1:8000/api/health)"
echo -n "  HTTPS (expect 401 = cert OK + password lock active): "
for i in $(seq 1 18); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 https://${DOMAIN}/api/health 2>/dev/null || echo 000)"
  if [ "$CODE" != "000" ]; then echo "HTTP $CODE"; break; fi
  sleep 5
done
echo ""
echo "DONE. Open: https://${DOMAIN}/   (user: admin, password from setup)"
echo "Webhook status: curl -s \"https://api.telegram.org/bot\${TOKEN}/getWebhookInfo\""
