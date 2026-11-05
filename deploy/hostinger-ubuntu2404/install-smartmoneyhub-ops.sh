#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this installer as root."
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
SITE_SOURCE="$BUNDLE_ROOT/site"
SITE_ROOT="/var/www/smartmoneyhub-ops"
NGINX_SOURCE="$SCRIPT_DIR/smartmoneyhub-ops.nginx.conf"
NGINX_TARGET="/etc/nginx/sites-available/smartmoneyhub.tech"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/opt/smart-money-hub/ops-web-backups/$STAMP"

if ! command -v nginx >/dev/null 2>&1; then
  echo "Nginx is not installed. Install it with: apt update && apt install -y nginx"
  exit 1
fi
if [[ ! -d "$SITE_SOURCE" || ! -s "$SITE_SOURCE/index.html" ]]; then
  echo "The bundled site/ directory or index.html is missing."
  exit 1
fi
if [[ ! -s "$NGINX_SOURCE" ]]; then
  echo "The bundled Nginx configuration is missing."
  exit 1
fi

mkdir -p "$BACKUP_DIR"
if [[ -d "$SITE_ROOT" ]]; then
  cp -a "$SITE_ROOT" "$BACKUP_DIR/site"
fi
if [[ -e "$NGINX_TARGET" ]]; then
  cp -a "$NGINX_TARGET" "$BACKUP_DIR/smartmoneyhub.tech"
fi

install -d -m 755 "$SITE_ROOT"
cp -a "$SITE_SOURCE/." "$SITE_ROOT/"
install -D -m 644 "$NGINX_SOURCE" "$NGINX_TARGET"
ln -sfn "$NGINX_TARGET" /etc/nginx/sites-enabled/smartmoneyhub.tech

if ! nginx -t; then
  echo "Nginx validation failed. The previous files, if any, are backed up in $BACKUP_DIR."
  exit 1
fi

systemctl enable --now nginx
systemctl reload nginx
curl -fsS -H 'Host: smartmoneyhub.tech' http://127.0.0.1/ >/dev/null
printf 'Health endpoint response: '
curl -fsS -H 'Host: smartmoneyhub.tech' http://127.0.0.1/api/healthz
printf '\nSite installed. Backup directory: %s\n' "$BACKUP_DIR"
echo "DNS has not been changed. Wait for the owner to verify the site before repointing the domain."
