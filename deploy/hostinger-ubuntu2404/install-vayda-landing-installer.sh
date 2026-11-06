#!/usr/bin/env bash
# Self-extracting installer template. Build the uploadable installer with
# build-vayda-landing-installer.sh; do not run this source template directly.
set -Eeuo pipefail

PAYLOAD_MARKER="__SMH_VAYDA_LANDING_PAYLOAD__"
INSTALLER_VERSION="landing-v5-root-mapping"
SCRIPT_PATH="$(readlink -f "$0")"
PAYLOAD_LINE="$(awk -v marker="$PAYLOAD_MARKER" '$0 == marker { print NR; exit }' "$SCRIPT_PATH")"

if [[ -z "$PAYLOAD_LINE" ]]; then
  echo "ERROR: Embedded landing package is missing. Use the generated installer file." >&2
  exit 1
fi
echo "Installer version: ${INSTALLER_VERSION}"

WORK_DIR="$(mktemp -d /tmp/smh-vayda-landing.XXXXXX)"
NGINX_TMP=""
BACKUP=""
NGINX_REAL=""
LANDING_BASE="/var/www/smh-vayda-landing"
CURRENT="${LANDING_BASE}/current"
LANDING_DIR="/var/www/_vayda_landing"
STAGING_DIR=""
PREVIOUS_DIR=""
NGINX_CHANGED=0
STAGING_CREATED=0
ASSETS_INSTALLED=0
PREVIOUS_ASSETS=0
ROLLBACK_ENABLED=1

cleanup() {
  [[ -z "$NGINX_TMP" ]] || rm -f "$NGINX_TMP"
  if [[ "$STAGING_CREATED" == "1" && -n "$STAGING_DIR" && -d "$STAGING_DIR" ]]; then
    rm -rf "$STAGING_DIR"
  fi
  [[ -z "$WORK_DIR" ]] || rm -rf "$WORK_DIR"
}

rollback() {
  set +e
  if [[ "$NGINX_CHANGED" == "1" && -n "$BACKUP" && -n "$NGINX_REAL" ]]; then
    local restore_tmp
    restore_tmp="$(mktemp "${NGINX_REAL}.restore.XXXXXX")"
    cp -a "$BACKUP/nginx-site.conf" "$restore_tmp" &&
      mv -f "$restore_tmp" "$NGINX_REAL" &&
      nginx -t >/dev/null 2>&1 &&
      systemctl reload nginx
    NGINX_CHANGED=0
  fi
  if [[ "$ASSETS_INSTALLED" == "1" && -d "$LANDING_DIR" ]]; then
    rm -rf "$LANDING_DIR"
    ASSETS_INSTALLED=0
  fi
  if [[ "$PREVIOUS_ASSETS" == "1" && -d "$PREVIOUS_DIR" && ! -e "$LANDING_DIR" ]]; then
    mv "$PREVIOUS_DIR" "$LANDING_DIR"
    PREVIOUS_ASSETS=0
  fi
  if [[ "$STAGING_CREATED" == "1" && -n "$STAGING_DIR" && -d "$STAGING_DIR" ]]; then
    rm -rf "$STAGING_DIR"
    STAGING_CREATED=0
  fi
  set -e
}

on_error() {
  local status=$?
  if [[ "$ROLLBACK_ENABLED" == "1" ]]; then
    rollback
    echo "ERROR: Installation stopped; any changed landing route was rolled back." >&2
  fi
  exit "$status"
}

fail() {
  echo "ERROR: $*" >&2
  if [[ "$ROLLBACK_ENABLED" == "1" ]]; then
    rollback
  fi
  exit 1
}

trap cleanup EXIT
trap on_error ERR

tail -n +"$((PAYLOAD_LINE + 1))" "$SCRIPT_PATH" | tar -xzf - -C "$WORK_DIR"
[[ -s "$WORK_DIR/SHA256SUMS" ]] || fail "Package checksum list is missing."
(cd "$WORK_DIR" && sha256sum -c SHA256SUMS >/dev/null) || fail "Package checksum verification failed."
[[ -s "$WORK_DIR/site/index.html" ]] || fail "Landing page index.html is missing."
[[ -s "$WORK_DIR/patch-vayda-landing-nginx.py" ]] || fail "Nginx route patcher is missing."
python3 "$WORK_DIR/patch-vayda-landing-nginx.py" --self-test || fail "Nginx patcher self-test failed."

if [[ "${1:-}" == "--check-package" ]]; then
  if grep -R -E 'pk_(test|live)_[A-Za-z0-9]+|CLERK_SECRET_KEY|sk_(test|live)_[A-Za-z0-9]+' "$WORK_DIR/site"; then
    fail "A credential-like value was found in the static landing bundle."
  fi
  echo "Package checks passed: landing files, checksums, Nginx patcher, no auth credentials."
  exit 0
fi

[[ "$#" -eq 0 ]] || fail "This installer accepts no arguments other than --check-package."
[[ "$EUID" -eq 0 ]] || fail "Run this installer as root from Termius."
for command_name in nginx curl python3 systemctl tar sha256sum; do
  command -v "$command_name" >/dev/null 2>&1 || fail "Required command is missing: $command_name"
done

NGINX_SITE="/etc/nginx/sites-enabled/smartmoneyhub.tech"
WEB_ROOT="/var/www/smartmoneyhub-ops"
[[ -f "$NGINX_SITE" ]] || fail "The expected smartmoneyhub.tech Nginx site file was not found."
NGINX_REAL="$(readlink -f "$NGINX_SITE")"
[[ -f "$NGINX_REAL" ]] || fail "Could not resolve the active Nginx site file."
[[ -f "${WEB_ROOT}/index.html" ]] || fail "The existing Operations Center web root is missing."
[[ -f /etc/nginx/.smh-ops-users ]] || fail "The existing Operations Center Basic Auth file is missing."
systemctl is-active --quiet nginx || fail "Nginx is not active."
systemctl is-active --quiet smh-support-api.service || fail "The existing Support API is not active."
nginx -t >/dev/null || fail "The current Nginx configuration does not pass validation."

grep -Fq "server_name smartmoneyhub.tech www.smartmoneyhub.tech;" "$NGINX_REAL" ||
  fail "The active site file does not match the reviewed smartmoneyhub.tech host."
grep -Fq "root /var/www/smartmoneyhub-ops;" "$NGINX_REAL" ||
  fail "The existing Operations Center web root differs from the reviewed path."

request_code() {
  local host="$1" route="$2" response
  response="$(curl --silent --show-error --max-time 8 --insecure \
    --resolve "${host}:443:127.0.0.1" --output /dev/null --write-out '%{http_code}' \
    "https://${host}${route}" 2>/dev/null || true)"
  [[ "$response" =~ ^[0-9]{3}$ ]] || response="000"
  printf '%s' "$response"
}

api_session_request() {
  local body_path="$1" response
  response="$(curl --silent --show-error --max-time 8 --insecure \
    --resolve "smartmoneyhub.tech:443:127.0.0.1" --output "$body_path" --write-out '%{http_code}' \
    "https://smartmoneyhub.tech/api/support/auth/session" 2>/dev/null || true)"
  [[ "$response" =~ ^[0-9]{3}$ ]] || response="000"
  printf '%s' "$response"
}

validate_anonymous_session() {
  python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path

try:
    response = json.loads(Path(sys.argv[1]).read_text())
except Exception as error:
    raise SystemExit(f"Support API returned HTTP 200 but not a valid session response: {error}")
if response.get("authenticated") is not False or response.get("staff") is not None:
    raise SystemExit("Support API returned an authenticated staff identity without credentials.")
PY
}

OPS_BEFORE="$(request_code smartmoneyhub.tech /operations)"
API_BEFORE="$(api_session_request "$WORK_DIR/api-session-before.json")"
LOGIN_BEFORE="$(request_code smartmoneyhub.tech /login)"
[[ "$OPS_BEFORE" == "401" || "$OPS_BEFORE" == "403" ]] ||
  fail "The existing /operations Basic Auth check did not return 401/403 (got ${OPS_BEFORE}); no changes made."
if [[ "$API_BEFORE" == "200" ]]; then
  validate_anonymous_session "$WORK_DIR/api-session-before.json" ||
    fail "The Support API 200 response was not an anonymous session; no changes made."
elif [[ "$API_BEFORE" != "401" && "$API_BEFORE" != "403" ]]; then
  fail "The Support API session check returned unexpected status ${API_BEFORE}; no changes made."
fi
[[ "$LOGIN_BEFORE" != "000" && "$LOGIN_BEFORE" != "500" ]] ||
  fail "The existing /login route is not healthy (got ${LOGIN_BEFORE}); no changes made."

cat <<'NOTICE'
This will install the landing page at /, serve its static assets, redirect public
marketing paths to /, and keep sign-up closed. It preserves the existing /login,
/operations Basic Auth, /api routes, Support API, bot services, database and DNS.
It reloads Nginx only; it does not restart bots or APIs.
NOTICE
read -r -p 'Type INSTALL VAYDA LANDING to continue: ' confirmation
[[ "$confirmation" == "INSTALL VAYDA LANDING" ]] || {
  echo "No changes made."
  exit 0
}

TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP="/var/backups/smh-vayda-landing/${TIMESTAMP}"
STAGING_DIR="/var/www/.smh-vayda-landing-${TIMESTAMP}"
PREVIOUS_DIR="/var/www/_vayda_landing.previous-${TIMESTAMP}"
mkdir -p "$BACKUP"
chmod 700 "$BACKUP"
cp -a "$NGINX_REAL" "$BACKUP/nginx-site.conf"
chmod 600 "$BACKUP/nginx-site.conf"

[[ ! -e "$STAGING_DIR" ]] || fail "The temporary landing directory already exists."
[[ ! -e "$PREVIOUS_DIR" ]] || fail "The previous landing backup directory already exists."
if [[ -L "$LANDING_DIR" ]]; then
  fail "The static landing path is a symlink; refusing to replace an unreviewed target."
fi
if [[ -e "$LANDING_DIR" && ! -d "$LANDING_DIR" ]]; then
  fail "The static landing path exists but is not a directory."
fi
mkdir -m 755 "$STAGING_DIR"
STAGING_CREATED=1
cp -a "$WORK_DIR/site/." "$STAGING_DIR/"
find "$STAGING_DIR" -type d -exec chmod 755 {} +
find "$STAGING_DIR" -type f -exec chmod 644 {} +
[[ -s "$STAGING_DIR/index.html" ]] || fail "The staged landing index is missing."
grep -q "VAYDA Smart Money Hub" "$STAGING_DIR/index.html" ||
  fail "The staged landing index does not contain the expected site title."

if [[ -d "$LANDING_DIR" ]]; then
  mv "$LANDING_DIR" "$PREVIOUS_DIR"
  PREVIOUS_ASSETS=1
fi
mv "$STAGING_DIR" "$LANDING_DIR"
STAGING_CREATED=0
ASSETS_INSTALLED=1

NGINX_TMP="$(mktemp "${NGINX_REAL}.landing.XXXXXX")"
python3 "$WORK_DIR/patch-vayda-landing-nginx.py" "$NGINX_REAL" "$NGINX_TMP" ||
  fail "The active HTTPS configuration differs from the reviewed layout; no route was changed."
chown --reference="$NGINX_REAL" "$NGINX_TMP"
chmod --reference="$NGINX_REAL" "$NGINX_TMP"

mv -f "$NGINX_TMP" "$NGINX_REAL"
NGINX_TMP=""
NGINX_CHANGED=1
nginx -t >/dev/null || fail "Nginx validation failed after the route update."
nginx -T > "$WORK_DIR/nginx-effective.conf" 2>&1 ||
  fail "Nginx could not print its active configuration after the route update."
grep -Fq "$LANDING_DIR" "$WORK_DIR/nginx-effective.conf" ||
  fail "The updated landing routes are not present in Nginx's loaded configuration."
systemctl reload nginx || fail "Nginx reload failed."

ASSET_INDEX="${WORK_DIR}/asset-index.html"
curl --silent --show-error --fail --max-time 10 --insecure \
  --resolve smartmoneyhub.tech:443:127.0.0.1 \
  "https://smartmoneyhub.tech/_vayda_landing/index.html" -o "$ASSET_INDEX" ||
  fail "Nginx did not serve the versioned landing files at /_vayda_landing/."
grep -q "VAYDA Smart Money Hub" "$ASSET_INDEX" ||
  fail "The static asset route did not return the VAYDA landing HTML."

for host in smartmoneyhub.tech www.smartmoneyhub.tech; do
  root_file="${WORK_DIR}/${host}.html"
  ROOT_OK=0
  for attempt in 1 2 3 4 5 6 7 8; do
    if curl --silent --show-error --fail --max-time 10 --insecure \
      --resolve "${host}:443:127.0.0.1" "https://${host}/" -o "$root_file" 2>/dev/null &&
      grep -q "VAYDA Smart Money Hub" "$root_file"; then
      ROOT_OK=1
      break
    fi
    sleep 1
  done
  if [[ "$ROOT_OK" != "1" ]]; then
    echo "Homepage response title: $(grep -o '<title>[^<]*</title>' "$root_file" 2>/dev/null | head -n 1 || true)" >&2
    echo "Loaded landing routes:" >&2
    grep -n -A8 -B2 'SMH VAYDA LANDING' "$WORK_DIR/nginx-effective.conf" | head -n 30 >&2 || true
    fail "Nginx served the static landing file but did not route / to it for ${host}."
  fi
done

ASSET_PATH="$(grep -oE 'src="/_vayda_landing/[^"]+\.js"' "$WORK_DIR/site/index.html" |
  head -n 1 | cut -d '"' -f 2)"
[[ -n "$ASSET_PATH" ]] || fail "Could not find the landing JavaScript asset path."
curl --silent --show-error --fail --max-time 10 --insecure \
  --resolve smartmoneyhub.tech:443:127.0.0.1 \
  "https://smartmoneyhub.tech${ASSET_PATH}" -o /dev/null ||
  fail "The landing JavaScript asset did not load."

OPS_AFTER="$(request_code smartmoneyhub.tech /operations)"
API_AFTER="$(api_session_request "$WORK_DIR/api-session-after.json")"
LOGIN_AFTER="$(request_code smartmoneyhub.tech /login)"
SIGNUP_AFTER="$(request_code smartmoneyhub.tech /sign-up)"
MARKET_AFTER="$(request_code smartmoneyhub.tech /market-analysis)"
[[ "$OPS_AFTER" == "$OPS_BEFORE" ]] || fail "The /operations access response changed."
[[ "$API_AFTER" == "$API_BEFORE" ]] || fail "The Support API access response changed."
if [[ "$API_AFTER" == "200" ]]; then
  validate_anonymous_session "$WORK_DIR/api-session-after.json" ||
    fail "The Support API no longer returns an anonymous session."
  python3 - "$WORK_DIR/api-session-before.json" "$WORK_DIR/api-session-after.json" <<'PY' ||
import json
import sys
from pathlib import Path

before = json.loads(Path(sys.argv[1]).read_text())
after = json.loads(Path(sys.argv[2]).read_text())
if before != after:
    raise SystemExit("The Support API session response changed.")
PY
    fail "The Support API session response changed."
fi
[[ "$LOGIN_AFTER" == "$LOGIN_BEFORE" ]] || fail "The /login response changed."
[[ "$SIGNUP_AFTER" == "302" ]] || fail "The closed /sign-up route did not redirect to the landing page."
[[ "$MARKET_AFTER" == "302" ]] || fail "The public marketing route did not redirect to the landing page."

ROLLBACK_ENABLED=0
NGINX_CHANGED=0
ASSETS_INSTALLED=0
PREVIOUS_ASSETS=0
if [[ -L "$CURRENT" ]] && [[ "$(readlink "$CURRENT")" == "$CURRENT" ]]; then
  printf '%s\n' "$(readlink "$CURRENT")" > "$BACKUP/stale-current-link.txt"
  chmod 600 "$BACKUP/stale-current-link.txt"
  rm -f "$CURRENT"
  echo "Removed the stale self-referential landing symlink."
fi
echo "Landing page installed at https://smartmoneyhub.tech and https://www.smartmoneyhub.tech."
echo "Verified: landing assets load; /login is unchanged; /sign-up is closed."
echo "Verified: /operations protection and the anonymous Support API session response are unchanged."
echo "No DNS, database, bot, Support API, or Production authentication settings were changed."
echo "Nginx backup: ${BACKUP}/nginx-site.conf"
if [[ -d "$PREVIOUS_DIR" ]]; then
  echo "Previous landing files backed up at: ${PREVIOUS_DIR}"
fi
exit 0

__SMH_VAYDA_LANDING_PAYLOAD__
