#!/usr/bin/env bash
# Self-extracting installer template. Build the uploadable installer with
# build-vayda-landing-installer.sh; do not run this source template directly.
set -Eeuo pipefail

PAYLOAD_MARKER="__SMH_VAYDA_LANDING_PAYLOAD__"
SCRIPT_PATH="$(readlink -f "$0")"
PAYLOAD_LINE="$(awk -v marker="$PAYLOAD_MARKER" '$0 == marker { print NR; exit }' "$SCRIPT_PATH")"

if [[ -z "$PAYLOAD_LINE" ]]; then
  echo "ERROR: Embedded landing package is missing. Use the generated installer file." >&2
  exit 1
fi

WORK_DIR="$(mktemp -d /tmp/smh-vayda-landing.XXXXXX)"
NGINX_TMP=""
BACKUP=""
NGINX_REAL=""
LANDING_BASE="/var/www/smh-vayda-landing"
CURRENT="${LANDING_BASE}/current"
RELEASE_DIR=""
PREVIOUS_TARGET=""
NGINX_CHANGED=0
LINK_CHANGED=0
ROLLBACK_ENABLED=1

cleanup() {
  [[ -z "$NGINX_TMP" ]] || rm -f "$NGINX_TMP"
  [[ -z "$WORK_DIR" ]] || rm -rf "$WORK_DIR"
}

rollback() {
  set +e
  if [[ "$LINK_CHANGED" == "1" ]]; then
    if [[ -n "$PREVIOUS_TARGET" ]]; then
      local rollback_link="${LANDING_BASE}/current.rollback"
      rm -f "$rollback_link"
      ln -s "$PREVIOUS_TARGET" "$rollback_link" &&
        mv -Tf "$rollback_link" "$CURRENT"
    else
      rm -f "$CURRENT"
    fi
    LINK_CHANGED=0
  fi
  if [[ "$NGINX_CHANGED" == "1" && -n "$BACKUP" && -n "$NGINX_REAL" ]]; then
    local restore_tmp
    restore_tmp="$(mktemp "${NGINX_REAL}.restore.XXXXXX")"
    cp -a "$BACKUP/nginx-site.conf" "$restore_tmp" &&
      mv -f "$restore_tmp" "$NGINX_REAL" &&
      nginx -t >/dev/null 2>&1 &&
      systemctl reload nginx
    NGINX_CHANGED=0
  fi
  if [[ -n "$RELEASE_DIR" && -d "$RELEASE_DIR" ]]; then
    rm -rf "$RELEASE_DIR"
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

OPS_BEFORE="$(request_code smartmoneyhub.tech /operations)"
API_BEFORE="$(request_code smartmoneyhub.tech /api/support/auth/session)"
LOGIN_BEFORE="$(request_code smartmoneyhub.tech /login)"
[[ "$OPS_BEFORE" == "401" || "$OPS_BEFORE" == "403" ]] ||
  fail "The existing /operations Basic Auth check did not return 401/403 (got ${OPS_BEFORE}); no changes made."
[[ "$API_BEFORE" == "401" || "$API_BEFORE" == "403" ]] ||
  fail "The existing unauthenticated Support API check did not return 401/403 (got ${API_BEFORE}); no changes made."
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
RELEASE_DIR="${LANDING_BASE}/releases/${TIMESTAMP}"
mkdir -p "$BACKUP" "${LANDING_BASE}/releases"
chmod 700 "$BACKUP"
cp -a "$NGINX_REAL" "$BACKUP/nginx-site.conf"
chmod 600 "$BACKUP/nginx-site.conf"

if [[ -e "$CURRENT" && ! -L "$CURRENT" ]]; then
  fail "The landing current path exists but is not a symlink; no files were replaced."
fi
PREVIOUS_TARGET="$(readlink -f "$CURRENT" 2>/dev/null || true)"
[[ ! -e "$RELEASE_DIR" ]] || fail "The release directory already exists."
mkdir -m 755 "$RELEASE_DIR"
cp -a "$WORK_DIR/site/." "$RELEASE_DIR/"
find "$RELEASE_DIR" -type d -exec chmod 755 {} +
find "$RELEASE_DIR" -type f -exec chmod 644 {} +

NGINX_TMP="$(mktemp "${NGINX_REAL}.landing.XXXXXX")"
python3 "$WORK_DIR/patch-vayda-landing-nginx.py" "$NGINX_REAL" "$NGINX_TMP" ||
  fail "The active HTTPS configuration differs from the reviewed layout; no route was changed."
chown --reference="$NGINX_REAL" "$NGINX_TMP"
chmod --reference="$NGINX_REAL" "$NGINX_TMP"

NEXT_LINK="${LANDING_BASE}/current.next"
rm -f "$NEXT_LINK"
ln -s "$RELEASE_DIR" "$NEXT_LINK"
mv -Tf "$NEXT_LINK" "$CURRENT"
LINK_CHANGED=1

mv -f "$NGINX_TMP" "$NGINX_REAL"
NGINX_TMP=""
NGINX_CHANGED=1
nginx -t >/dev/null || fail "Nginx validation failed after the route update."
systemctl reload nginx || fail "Nginx reload failed."

for host in smartmoneyhub.tech www.smartmoneyhub.tech; do
  root_file="${WORK_DIR}/${host}.html"
  curl --silent --show-error --fail --max-time 10 --insecure \
    --resolve "${host}:443:127.0.0.1" "https://${host}/" -o "$root_file" ||
    fail "The landing page did not load locally for ${host}."
  grep -q "VAYDA Smart Money Hub" "$root_file" ||
    fail "The served homepage is not the VAYDA landing page for ${host}."
done

ASSET_PATH="$(grep -oE 'src="/_vayda_landing/[^"]+\.js"' "$WORK_DIR/site/index.html" |
  head -n 1 | cut -d '"' -f 2)"
[[ -n "$ASSET_PATH" ]] || fail "Could not find the landing JavaScript asset path."
curl --silent --show-error --fail --max-time 10 --insecure \
  --resolve smartmoneyhub.tech:443:127.0.0.1 \
  "https://smartmoneyhub.tech${ASSET_PATH}" -o /dev/null ||
  fail "The landing JavaScript asset did not load."

OPS_AFTER="$(request_code smartmoneyhub.tech /operations)"
API_AFTER="$(request_code smartmoneyhub.tech /api/support/auth/session)"
LOGIN_AFTER="$(request_code smartmoneyhub.tech /login)"
SIGNUP_AFTER="$(request_code smartmoneyhub.tech /sign-up)"
MARKET_AFTER="$(request_code smartmoneyhub.tech /market-analysis)"
[[ "$OPS_AFTER" == "$OPS_BEFORE" ]] || fail "The /operations access response changed."
[[ "$API_AFTER" == "$API_BEFORE" ]] || fail "The Support API access response changed."
[[ "$LOGIN_AFTER" == "$LOGIN_BEFORE" ]] || fail "The /login response changed."
[[ "$SIGNUP_AFTER" == "302" ]] || fail "The closed /sign-up route did not redirect to the landing page."
[[ "$MARKET_AFTER" == "302" ]] || fail "The public marketing route did not redirect to the landing page."

ROLLBACK_ENABLED=0
NGINX_CHANGED=0
LINK_CHANGED=0
echo "Landing page installed at https://smartmoneyhub.tech and https://www.smartmoneyhub.tech."
echo "Verified: landing assets load; /login is unchanged; /sign-up is closed."
echo "Verified: /operations and Support API access responses are unchanged."
echo "No DNS, database, bot, Support API, or Production authentication settings were changed."
echo "Nginx backup: ${BACKUP}/nginx-site.conf"
echo "To roll back manually, restore that Nginx file and point ${CURRENT} back to: ${PREVIOUS_TARGET:-no previous release}"
exit 0

__SMH_VAYDA_LANDING_PAYLOAD__
