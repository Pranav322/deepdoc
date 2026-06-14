#!/usr/bin/env bash
# Run ONCE on the droplet to set up deepdoc server.
# From your local machine:
#   scp -i ~/.ssh/contextly_deploy web/server/setup.sh root@143.110.247.23:/tmp/
#   ssh -i ~/.ssh/contextly_deploy root@143.110.247.23 bash /tmp/setup.sh
set -euo pipefail

echo "==> System packages..."
apt-get update -qq
apt-get install -y -qq git curl build-essential python3 python3-pip python3-venv

echo "==> Node.js 20..."
if ! command -v node &>/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
else
  echo "  node $(node -v) already installed, skipping."
fi

echo "==> /data directory..."
mkdir -p /data

echo "==> deepdoc..."
# Install from PyPI. If not published yet, replace with:
#   git clone https://github.com/YOUR_ORG/codewiki /opt/codewiki
#   pip3 install -e /opt/codewiki --break-system-packages
pip3 install deepdoc mkdocs-material mkdocs-swagger-ui-tag --break-system-packages 2>/dev/null || \
  pip3 install deepdoc mkdocs-material mkdocs-swagger-ui-tag --break-system-packages --upgrade

echo "==> deepdoc check..."
deepdoc --version || deepdoc --help | head -1

echo "==> Server files..."
mkdir -p /opt/deepdoc-server
# Files are expected at /tmp/deepdoc-server/ — deploy.sh puts them there
cp -r /tmp/deepdoc-server/server/* /opt/deepdoc-server/
cd /opt/deepdoc-server && npm install --omit=dev

echo "==> .env..."
if [ ! -f /opt/deepdoc-server/.env ]; then
  cp /opt/deepdoc-server/.env.example /opt/deepdoc-server/.env
  echo ""
  echo "  !! Fill in /opt/deepdoc-server/.env with Azure keys before starting !!"
  echo ""
fi

echo "==> Systemd service..."
cat > /etc/systemd/system/deepdoc-server.service << 'EOF'
[Unit]
Description=DeepDoc hosted generation server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/deepdoc-server
EnvironmentFile=/opt/deepdoc-server/.env
ExecStart=/usr/bin/node /opt/deepdoc-server/index.js
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable deepdoc-server

echo "==> Firewall: opening port 3001..."
# Caddy owns 80/443 — we do NOT touch those.
# deepdoc server runs on 3001, CF Function calls it directly via raw IP.
ufw allow 3001/tcp comment "deepdoc-server" 2>/dev/null || true

echo ""
echo "==> Edit .env then start the server:"
echo "    nano /opt/deepdoc-server/.env"
echo "    systemctl start deepdoc-server"
echo "    journalctl -u deepdoc-server -f"
echo ""
echo "✓ Setup complete. Caddy is untouched."
echo "  Set BACKEND_URL=http://143.110.247.23:3001 in Cloudflare Pages env vars."
