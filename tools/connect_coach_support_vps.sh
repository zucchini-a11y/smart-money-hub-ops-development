#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "Run this command as root."

readonly SUPPORT_API_ENV="/etc/smh-support-api.env"
readonly COACH_ENV="/etc/smart-money-hub.env"
readonly SUPPORT_API_SERVICE="smh-support-api.service"
readonly COACH_SERVICE="smart-money-hub.service"
readonly SUPPORT_API_PORT="23827"
readonly SUPPORT_API_ROOT="http://127.0.0.1:${SUPPORT_API_PORT}"
readonly SUPPORT_API_PUBLIC_URL="https://smartmoneyhub.tech"
readonly COACH_APP="/opt/smart-money-hub/app"
readonly STAMP="$(date -u +%Y%m%d-%H%M%S)"
readonly BACKUP_DIR="/var/backups/smh-support-portal/coach-connection-${STAMP}"
readonly TOKEN_FILE="/run/smh-coach-support-token-${STAMP}"

CONFIG_CHANGED=0
API_RESTART_ATTEMPTED=0
COACH_RESTART_ATTEMPTED=0
SUCCESS=0

restore_on_failure() {
  status=$?
  if [[ "$SUCCESS" -ne 1 && "$CONFIG_CHANGED" -eq 1 ]]; then
    printf 'The connection check failed; restoring the saved environment files.\n' >&2
    cp -a "${BACKUP_DIR}/smh-support-api.env" "$SUPPORT_API_ENV" || true
    cp -a "${BACKUP_DIR}/smart-money-hub.env" "$COACH_ENV" || true
    chown root:root "$SUPPORT_API_ENV" "$COACH_ENV" || true
    chmod 600 "$SUPPORT_API_ENV" "$COACH_ENV" || true
    if [[ "$API_RESTART_ATTEMPTED" -eq 1 ]]; then
      systemctl restart "$SUPPORT_API_SERVICE" >/dev/null 2>&1 || true
    fi
    if [[ "$COACH_RESTART_ATTEMPTED" -eq 1 ]]; then
      systemctl restart "$COACH_SERVICE" >/dev/null 2>&1 || true
    fi
  fi
  rm -f "$TOKEN_FILE"
  return "$status"
}
trap restore_on_failure EXIT

for command_name in python3 systemctl curl cp chmod chown grep mkdir date sleep; do
  command -v "$command_name" >/dev/null 2>&1 || fail "Required command is missing: ${command_name}."
done

[[ -r "$SUPPORT_API_ENV" ]] || fail "The Support API environment file is missing."
[[ -r "$COACH_ENV" ]] || fail "The Coach bot environment file is missing."
[[ -f "/etc/systemd/system/${SUPPORT_API_SERVICE}" ]] || fail "The Support API service unit is missing."
[[ -f "/etc/systemd/system/${COACH_SERVICE}" ]] || fail "The Coach service unit is missing."
grep -Fq "EnvironmentFile=${SUPPORT_API_ENV}" "/etc/systemd/system/${SUPPORT_API_SERVICE}" \
  || fail "The Support API service does not use the expected environment file."
grep -Fq "EnvironmentFile=${COACH_ENV}" "/etc/systemd/system/${COACH_SERVICE}" \
  || fail "The Coach service does not use the expected environment file."

[[ -f "${COACH_APP}/smart_money_hub_bot/support_api.py" ]] \
  || fail "The installed Coach source lacks the shared support client; no changes were made."
grep -q "SupportApiClient" "${COACH_APP}/smart_money_hub_bot/bot.py" \
  || fail "The installed Coach source lacks the portal reply worker; no changes were made."

systemctl is-active --quiet "$SUPPORT_API_SERVICE" \
  || fail "The Support API is not active; no changes were made."
systemctl is-active --quiet "$COACH_SERVICE" \
  || fail "The existing Coach service is not active; no changes were made."

python3 - "$SUPPORT_API_ENV" "$COACH_ENV" <<'PY'
import sys
from pathlib import Path

def read_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.startswith(("'", '"')) and value.endswith(value[0]):
            value = value[1:-1]
        values[key] = value
    return values

api = read_env(sys.argv[1])
coach = read_env(sys.argv[2])
if not api.get("SMH_DATABASE_URL"):
    raise SystemExit("The Support API database setting is missing; no changes were made.")
if api.get("NODE_ENV") != "production" or api.get("SMH_SUPPORT_SCHEMA") != "smh":
    raise SystemExit("The API is not configured for the expected Production schema; no changes were made.")
if api.get("SMH_SUPPORT_PRODUCTION_ENABLED") != "true":
    raise SystemExit("Production support is not enabled in the API; no changes were made.")
if not coach.get("TELEGRAM_BOT_TOKEN"):
    raise SystemExit("The live Coach Telegram configuration is incomplete; no changes were made.")
if coach.get("SMH_ISOLATED_TEST_INSTANCE", "").casefold() in {"1", "true", "yes"}:
    raise SystemExit("The Coach service is marked as an isolated test bot; no changes were made.")
PY

curl --fail --silent --max-time 3 -o /dev/null \
  "${SUPPORT_API_ROOT}/api/support/auth/session" \
  || fail "The current Support API health check failed; no changes were made."

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
cp -a "$SUPPORT_API_ENV" "${BACKUP_DIR}/smh-support-api.env"
cp -a "$COACH_ENV" "${BACKUP_DIR}/smart-money-hub.env"

# Reuse an existing matching Coach token when available; otherwise create one
# locally on the VPS. Never print or place the token in this source package.
python3 - "$SUPPORT_API_ENV" "$COACH_ENV" > "$TOKEN_FILE" <<'PY'
import secrets
import sys
from pathlib import Path

def token_from(path):
    for line in Path(path).read_text().splitlines():
        if line.startswith("SMH_SUPPORT_COACH_TOKEN="):
            value = line.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return ""

api_token = token_from(sys.argv[1])
coach_token = token_from(sys.argv[2])
if api_token and coach_token and api_token != coach_token:
    raise SystemExit("Existing Coach tokens differ; no changes were made.")
token = api_token or coach_token or secrets.token_urlsafe(48)
if len(token) < 32:
    raise SystemExit("An existing Coach token is too short; no changes were made.")
print(token)
PY
chmod 600 "$TOKEN_FILE"

CONFIG_CHANGED=1
python3 - "$SUPPORT_API_ENV" "$COACH_ENV" "$TOKEN_FILE" "$SUPPORT_API_PUBLIC_URL" <<'PY'
import os
import re
import sys
import tempfile
from pathlib import Path

api_path = Path(sys.argv[1])
coach_path = Path(sys.argv[2])
token_path = Path(sys.argv[3])
api_url = sys.argv[4]
token = token_path.read_text().strip()
if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
    raise SystemExit("The Coach token is invalid; no settings were changed.")

def write_env(path, updates):
    existing = path.read_text().splitlines()
    keys = set(updates)
    kept = [
        line
        for line in existing
        if not (
            line
            and not line.lstrip().startswith("#")
            and "=" in line
            and line.split("=", 1)[0] in keys
        )
    ]
    contents = "\n".join([*kept, *(f"{key}={value}" for key, value in updates.items())]).rstrip() + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, 0, 0)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

write_env(api_path, {"SMH_SUPPORT_COACH_TOKEN": token})
write_env(
    coach_path,
    {
        "SMH_SUPPORT_API_ENABLED": "true",
        "SMH_SUPPORT_PRODUCTION_ENABLED": "true",
        "SMH_SUPPORT_API_URL": api_url,
        "SMH_SUPPORT_COACH_TOKEN": token,
    },
)
PY

chown root:root "$SUPPORT_API_ENV" "$COACH_ENV"
chmod 600 "$SUPPORT_API_ENV" "$COACH_ENV"

wait_for_api() {
  for _ in {1..20}; do
    if curl --fail --silent --max-time 2 -o /dev/null \
      "${SUPPORT_API_ROOT}/api/support/auth/session"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

API_RESTART_ATTEMPTED=1
systemctl restart "$SUPPORT_API_SERVICE"
wait_for_api || fail "The Support API did not recover after its restart."

# Verify the Coach bearer token with a read-only request for a synthetic ID.
# Response content is validated but never printed.
SMH_COACH_TOKEN_FILE="$TOKEN_FILE" \
SMH_COACH_PROBE_URL="${SUPPORT_API_ROOT}/api/support/bot/cases?telegramUserId=9000000000000000" \
python3 - <<'PY'
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

token = Path(os.environ["SMH_COACH_TOKEN_FILE"]).read_text().strip()
request = Request(
    os.environ["SMH_COACH_PROBE_URL"],
    headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
)
try:
    with urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or payload.get("cases") != []:
            raise SystemExit("Coach API verification returned an unexpected result.")
except (HTTPError, URLError, TimeoutError, OSError, ValueError):
    raise SystemExit("Coach API token verification failed.")
PY

COACH_RESTART_ATTEMPTED=1
systemctl restart "$COACH_SERVICE"
systemctl is-active --quiet "$COACH_SERVICE" \
  || fail "The Coach service is not active after its restart."
wait_for_api || fail "The Support API health check failed after the Coach restart."

SUCCESS=1
printf 'Coach support connection enabled on the live shared portal.\n'
printf 'Support API and existing Coach service are active; no second bot process was started.\n'
printf 'No Telegram message was sent. Token stored in root-only environment files.\n'
printf 'Recovery copies: %s\n' "$BACKUP_DIR"
