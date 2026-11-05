#!/usr/bin/env bash
set -Eeuo pipefail

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "Run this installer as root."

readonly TRANSFER_DIR="/home/smh-support-transfer/incoming"
readonly BUNDLE="${TRANSFER_DIR}/smh-support-portal-deploy.tar.gz"
readonly CHECKSUM="${BUNDLE}.sha256"
readonly SIGNALS_ENV="/etc/smh-signals.env"
readonly SUPPORT_ENV="/etc/smh-support-api.env"
readonly NGINX_SITE="/etc/nginx/sites-enabled/smartmoneyhub.tech"
readonly WEB_ROOT="/var/www/smartmoneyhub-ops"
readonly API_ROOT="/opt/smh-support-api"
readonly SERVICE_FILE="/etc/systemd/system/smh-support-api.service"
readonly PORT="23827"
readonly STAMP="$(date -u +%Y%m%d-%H%M%S)"
readonly BACKUP="/var/backups/smh-support-portal/${STAMP}"
readonly WEB_OLD="/var/www/.smartmoneyhub-ops-old-${STAMP}"
readonly WEB_NEW="/var/www/.smartmoneyhub-ops-new-${STAMP}"

TEMP_DIR="$(mktemp -d /tmp/smh-support-portal.XXXXXX)"
NGINX_REAL=""
NGINX_BACKUP=""
OLD_API_LINK=""
OLD_SERVICE_EXISTS=0
OLD_ENV_EXISTS=0
WEB_SWAPPED=0
WEB_OLD_SAVED=0
NGINX_CHANGED=0
API_INSTALL_CHANGED=0
OLD_SERVICE_ACTIVE=0
SUCCESS=0

finish() {
  status=$?
  if [[ "$SUCCESS" -ne 1 ]]; then
    if [[ "$NGINX_CHANGED" -eq 1 && -n "$NGINX_REAL" && -f "$NGINX_BACKUP" ]]; then
      cp -a "$NGINX_BACKUP" "$NGINX_REAL" || true
      nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
    fi
    if [[ "$WEB_SWAPPED" -eq 1 || "$WEB_OLD_SAVED" -eq 1 ]]; then
      rm -rf "$WEB_ROOT"
      if [[ -e "$WEB_OLD" ]]; then
        mv "$WEB_OLD" "$WEB_ROOT" || true
      elif [[ -d "${BACKUP}/webroot" ]]; then
        mkdir -p "$WEB_ROOT"
        cp -a "${BACKUP}/webroot/." "$WEB_ROOT/" || true
      fi
    fi
    if [[ "$API_INSTALL_CHANGED" -eq 1 ]]; then
      systemctl stop smh-support-api.service >/dev/null 2>&1 || true
      if [[ -n "$OLD_API_LINK" ]]; then
        ln -sfn "$OLD_API_LINK" "${API_ROOT}/current"
      else
        rm -f "${API_ROOT}/current"
      fi
      if [[ "$OLD_SERVICE_EXISTS" -eq 1 ]]; then
        cp -a "$BACKUP/smh-support-api.service" "$SERVICE_FILE" || true
      else
        rm -f "$SERVICE_FILE"
      fi
      if [[ "$OLD_ENV_EXISTS" -eq 1 ]]; then
        cp -a "$BACKUP/smh-support-api.env" "$SUPPORT_ENV" || true
      else
        rm -f "$SUPPORT_ENV"
      fi
      systemctl daemon-reload >/dev/null 2>&1 || true
      if [[ "$OLD_SERVICE_ACTIVE" -eq 1 ]]; then
        systemctl start smh-support-api.service >/dev/null 2>&1 || true
      else
        systemctl disable smh-support-api.service >/dev/null 2>&1 || true
      fi
    fi
  fi
  rm -rf "$TEMP_DIR" || true
  return "$status"
}
trap finish EXIT

[[ -r "$BUNDLE" && -r "$CHECKSUM" ]] || fail "Upload the portal bundle and checksum to ${TRANSFER_DIR} first."
EXPECTED_SHA="$(tr -d '[:space:]' < "$CHECKSUM")"
ACTUAL_SHA="$(sha256sum "$BUNDLE" | awk '{print $1}')"
[[ "$EXPECTED_SHA" =~ ^[a-fA-F0-9]{64}$ && "$EXPECTED_SHA" == "$ACTUAL_SHA" ]] || fail "Portal bundle checksum mismatch."

for command_name in python3 psql pg_dump runuser nginx systemctl curl sha256sum tar; do
  command -v "$command_name" >/dev/null 2>&1 || fail "Required command is missing: ${command_name}."
done
command -v ss >/dev/null 2>&1 || fail "The ss utility is required for the port preflight."

if [[ ! -x /usr/bin/node ]]; then
  command -v apt-get >/dev/null 2>&1 || fail "Node.js 18+ is required; apt-get is unavailable."
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
fi
[[ -x /usr/bin/node ]] || fail "Node.js was not installed at /usr/bin/node."
NODE_MAJOR="$(/usr/bin/node -p 'Number(process.versions.node.split(".")[0])')"
[[ "$NODE_MAJOR" -ge 18 ]] || fail "Node.js 18 or newer is required."

[[ -r "$SIGNALS_ENV" ]] || fail "The existing Signal environment file is missing."
grep -q '^SMH_DATABASE_URL=' "$SIGNALS_ENV" || fail "SMH_DATABASE_URL is missing from the existing Signal environment file."
python3 - "$SIGNALS_ENV" <<'PY'
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

path = Path(sys.argv[1])
line = next((line for line in path.read_text().splitlines()
             if line.startswith("SMH_DATABASE_URL=")), None)
if line is None:
    raise SystemExit("SMH_DATABASE_URL was not found.")
value = line.split("=", 1)[1].strip()
if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
    value = value[1:-1]
parsed = urlsplit(value)
database = unquote(parsed.path.lstrip("/").split("/", 1)[0])
if database != "smh_signals":
    raise SystemExit("SMH_DATABASE_URL does not point to the expected smh_signals database.")
if parsed.hostname not in {None, "", "localhost", "127.0.0.1", "::1"}:
    raise SystemExit("The configured Signal database is not local; refusing to migrate a different target.")
PY

[[ -f "$NGINX_SITE" ]] || fail "The smartmoneyhub.tech Nginx site file is missing."
[[ -f /etc/nginx/.smh-ops-users ]] || fail "The existing Operations Center login file is missing."
NGINX_REAL="$(readlink -f "$NGINX_SITE")"
[[ -f "$NGINX_REAL" ]] || fail "Could not resolve the active Nginx site configuration."
NGINX_BACKUP="${BACKUP}/nginx-original"
[[ -d "$WEB_ROOT" ]] || fail "The existing Operations Center web root is missing."
grep -q 'server_name smartmoneyhub.tech www.smartmoneyhub.tech;' "$NGINX_REAL" || fail "The active Nginx file is not the expected smartmoneyhub.tech site."
grep -q 'root /var/www/smartmoneyhub-ops;' "$NGINX_REAL" || fail "The Nginx web root differs from the expected Operations Center path."

python3 - "$NGINX_REAL" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text()
api = re.compile(r"^[ \t]*location[ \t]+/api/[ \t]*\{[ \t]*\n[ \t]*return[ \t]+404;[ \t]*\n[ \t]*\}", re.M)
root = re.compile(r"^[ \t]*location[ \t]+/[ \t]*\{[ \t]*\n[ \t]*try_files[ \t]+\$uri[ \t]+\$uri/[ \t]+/index\.html;[ \t]*\n[ \t]*\}", re.M)
if len(api.findall(text)) != 1 or len(root.findall(text)) != 1:
    raise SystemExit("Nginx routes differ from the reviewed configuration; no changes were made.")
PY

nginx -t >/dev/null || fail "The current Nginx configuration does not pass validation."
runuser -u postgres -- psql -d smh_signals -v ON_ERROR_STOP=1 -Atqc \
  "SELECT to_regclass('smh.portal_users') IS NOT NULL AND to_regclass('smh.assistant_escalations') IS NOT NULL" \
  | grep -qx t || fail "The expected live support tables were not found."
ADMIN_COUNT="$(runuser -u postgres -- psql -d smh_signals -v ON_ERROR_STOP=1 -Atqc \
  "SELECT count(*) FROM smh.portal_users WHERE active AND role='admin' AND must_change_password=FALSE")"
[[ "$ADMIN_COUNT" =~ ^[0-9]+$ && "$ADMIN_COUNT" -gt 0 ]] || fail "No active admin with a completed password change was found; refusing to expose the portal."
if ss -ltn 2>/dev/null | grep -q ":${PORT}[[:space:]]"; then
  fail "Port ${PORT} is already in use."
fi

tar -xzf "$BUNDLE" -C "$TEMP_DIR"
[[ -s "${TEMP_DIR}/web/index.html" ]] || fail "The web build is missing from the bundle."
[[ -s "${TEMP_DIR}/api/index.mjs" ]] || fail "The API build is missing from the bundle."
[[ -s "${TEMP_DIR}/migrations/002_support_production.sql" ]] || fail "The production migration is missing from the bundle."
[[ -s "${TEMP_DIR}/SHA256SUMS" ]] || fail "The bundle's internal file checksums are missing."
(cd "$TEMP_DIR" && sha256sum -c SHA256SUMS >/dev/null) || fail "A file in the portal bundle failed checksum validation."

mkdir -p "$BACKUP" "$BACKUP/db"
chmod 700 "$BACKUP" "$BACKUP/db"
runuser -u postgres -- pg_dump -Fc -d smh_signals > "$BACKUP/db/smh_signals.dump"
chown root:root "$BACKUP/db/smh_signals.dump"
chmod 600 "$BACKUP/db/smh_signals.dump"
cp -a "$NGINX_REAL" "$NGINX_BACKUP"
mkdir -p "$BACKUP/webroot"
cp -a "$WEB_ROOT/." "$BACKUP/webroot/"

if [[ -f "$SUPPORT_ENV" ]]; then
  OLD_ENV_EXISTS=1
  cp -a "$SUPPORT_ENV" "$BACKUP/smh-support-api.env"
fi
if [[ -f "$SERVICE_FILE" ]]; then
  OLD_SERVICE_EXISTS=1
  cp -a "$SERVICE_FILE" "$BACKUP/smh-support-api.service"
  if systemctl is-active --quiet smh-support-api.service; then
    OLD_SERVICE_ACTIVE=1
  fi
fi
if [[ -L "${API_ROOT}/current" ]]; then
  OLD_API_LINK="$(readlink "${API_ROOT}/current")"
fi
runuser -u postgres -- psql -d smh_signals -v ON_ERROR_STOP=1 \
  -f - < "${TEMP_DIR}/migrations/002_support_production.sql"

if ! id smh-support-api >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin smh-support-api
fi
install -d -o root -g smh-support-api -m 0750 "${API_ROOT}/releases"
RELEASE="${API_ROOT}/releases/${STAMP}"
install -d -o root -g smh-support-api -m 0750 "$RELEASE"
cp -a "${TEMP_DIR}/api/." "$RELEASE/"
chown -R root:smh-support-api "$RELEASE"
find "$RELEASE" -type d -exec chmod 750 {} +
find "$RELEASE" -type f -exec chmod 640 {} +
ln -sfn "$RELEASE" "${API_ROOT}/current"
API_INSTALL_CHANGED=1

ENV_TEMP="$(mktemp /etc/smh-support-api.env.XXXXXX)"
grep '^SMH_DATABASE_URL=' "$SIGNALS_ENV" > "$ENV_TEMP"
if [[ -f "$SUPPORT_ENV" ]]; then
  awk -F= '!seen[$1]++ && $1 ~ /^SMH_SUPPORT_(SIGNALS|COACH)_TOKEN$/ { print }' "$SUPPORT_ENV" >> "$ENV_TEMP" || true
fi
cat >> "$ENV_TEMP" <<EOF
NODE_ENV=production
PORT=${PORT}
SMH_SUPPORT_SCHEMA=smh
SMH_SUPPORT_PRODUCTION_ENABLED=true
EOF
chown root:root "$ENV_TEMP"
chmod 600 "$ENV_TEMP"
mv -f "$ENV_TEMP" "$SUPPORT_ENV"

cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=Smart Money Hub Support Portal API
After=network.target postgresql.service

[Service]
Type=simple
User=smh-support-api
Group=smh-support-api
WorkingDirectory=/opt/smh-support-api/current
EnvironmentFile=/etc/smh-support-api.env
ExecStart=/usr/bin/node /opt/smh-support-api/current/index.mjs
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF
chmod 644 "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable --now smh-support-api.service

API_READY=0
for _ in $(seq 1 20); do
  if curl --fail --silent --max-time 2 -o /dev/null \
    "http://127.0.0.1:${PORT}/api/support/auth/session"; then
    API_READY=1
    break
  fi
  sleep 1
done
if [[ "$API_READY" -ne 1 ]]; then
  fail "The API failed its local database-backed health check. Existing website and Nginx were not changed."
fi

python3 - "$NGINX_REAL" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
api = re.compile(r"^[ \t]*location[ \t]+/api/[ \t]*\{[ \t]*\n[ \t]*return[ \t]+404;[ \t]*\n[ \t]*\}", re.M)
root = re.compile(r"^[ \t]*location[ \t]+/[ \t]*\{[ \t]*\n[ \t]*try_files[ \t]+\$uri[ \t]+\$uri/[ \t]+/index\.html;[ \t]*\n[ \t]*\}", re.M)
api_block = """    location /api/ {
        auth_basic off;
        proxy_pass http://127.0.0.1:23827;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }"""
root_block = """    location ^~ /operations {
        auth_basic "Smart Money Hub Operations";
        auth_basic_user_file /etc/nginx/.smh-ops-users;
        try_files $uri $uri/ /index.html;
    }

    location / {
        auth_basic off;
        try_files $uri $uri/ /index.html;
    }"""
text, api_count = api.subn(api_block, text, count=1)
text, root_count = root.subn(root_block, text, count=1)
if api_count != 1 or root_count != 1:
    raise SystemExit("Nginx configuration changed after preflight; aborting.")
path.write_text(text)
PY
NGINX_CHANGED=1

cp -a "${TEMP_DIR}/web" "$WEB_NEW"
if [[ -e "$WEB_ROOT" ]]; then
  mv "$WEB_ROOT" "$WEB_OLD"
  WEB_OLD_SAVED=1
fi
if ! mv "$WEB_NEW" "$WEB_ROOT"; then
  fail "Could not install the new website; the previous site was restored."
fi
WEB_SWAPPED=1

if ! nginx -t >/dev/null || ! systemctl reload nginx; then
  fail "Nginx validation or reload failed; the previous website and config were restored."
fi

rm -rf "$WEB_OLD"
WEB_OLD_SAVED=0
WEB_SWAPPED=0
NGINX_CHANGED=0
SUCCESS=1
printf 'Support Portal is live at https://smartmoneyhub.tech\n'
printf 'API health check passed on 127.0.0.1:%s\n' "$PORT"
printf 'Database backup: %s/db/smh_signals.dump\n' "$BACKUP"
printf 'Operations Center Basic Auth remains enabled at /operations.\n'
printf 'Bot credentials were not changed; bot connections remain disabled until configured separately.\n'
