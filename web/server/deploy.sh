#!/usr/bin/env bash
# Push server code updates to the droplet.
# Run from repo root: bash web/server/deploy.sh
set -euo pipefail

DROPLET_IP="143.110.247.23"
SSH_KEY="$HOME/.ssh/contextly_deploy"
REMOTE="/opt/deepdoc-server"

echo "==> Uploading server files..."
scp -i "$SSH_KEY" -r web/server web/nginx \
  root@${DROPLET_IP}:/tmp/deepdoc-server

echo "==> Applying on droplet..."
ssh -i "$SSH_KEY" root@${DROPLET_IP} bash << 'REMOTE'
  set -e
  SRC=/tmp/deepdoc-server/server
  DEST=/opt/deepdoc-server

  cp "$SRC/index.js"   "$DEST/"
  cp "$SRC/jobs.js"    "$DEST/"
  cp "$SRC/queue.js"   "$DEST/"
  cp "$SRC/worker.js"  "$DEST/"
  cp "$SRC/package.json" "$DEST/"

  cd "$DEST" && npm install --omit=dev --prefer-offline

  echo "==> Upgrading deepdoc..."
  pip3 install --upgrade deepdoc --break-system-packages --ignore-installed
  # Note: site generation now uses Next.js — no mkdocs-material needed

  systemctl restart deepdoc-server
  echo "✓ Restarted."
  systemctl status deepdoc-server --no-pager | head -8
REMOTE

echo ""
echo "✓ Deploy done."
echo "  Logs: ssh -i ~/.ssh/contextly_deploy root@${DROPLET_IP} journalctl -u deepdoc-server -f"
