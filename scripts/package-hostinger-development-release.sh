#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 OUTPUT_ZIP" >&2
  exit 2
fi

root="$(git rev-parse --show-toplevel)"
output="$1"
work_dir="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/smh-dev-release.XXXXXX")"
package_dir="$work_dir/smh-portal-development"
trap 'rm -rf "$work_dir"' EXIT

portal_dist="$root/artifacts/smart-money-hub-ops/dist/public"
api_dist="$root/artifacts/api-server/dist"
development_migrations="$root/artifacts/api-server/migrations/portal-development"
api_assets="$root/artifacts/api-server/assets"

for required in "$portal_dist/index.html" "$api_dist/index.mjs" "$development_migrations"; do
  if [[ ! -e "$required" ]]; then
    echo "Required Development build output is missing: $required" >&2
    exit 1
  fi
done

mkdir -p "$package_dir/frontend" "$package_dir/api" "$package_dir/migrations"
cp -a "$portal_dist/." "$package_dir/frontend/"
cp -a "$api_dist/." "$package_dir/api/"
cp -a "$development_migrations/." "$package_dir/migrations/"

if [[ -d "$api_assets" ]]; then
  mkdir -p "$package_dir/api/assets"
  cp -a "$api_assets/." "$package_dir/api/assets/"
fi

cat > "$package_dir/BUILD-INFO.txt" <<EOF
Smart Money Hub Portal — Development release
Commit: $(git -C "$root" rev-parse HEAD)
Node.js build version: $(node --version)
Built at (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)
Scope: Portal frontend, API bundle, and Development-only migrations.
Database target: smh_test
EOF

cat > "$package_dir/DEPLOYMENT-NOTES.txt" <<'EOF'
This is a staged Development package, not an automatic VPS deployment.

Included:
- Built Portal frontend.
- Built Node API bundle and API runtime assets.
- Portal Development migrations only.

Not included:
- Passwords, API keys, database credentials, Clerk secret keys, or database data.
- Production migrations.
- Telegram bot processes or bot tokens.
- Nginx/systemd configuration or an activation script.

Do not apply migrations outside the isolated Development database (smh_test).
Do not point Production at this package. The active Development service, route,
database connection, and rollback target must be verified before activation.
EOF

mkdir -p "$(dirname "$output")"
rm -f "$output"
(
  cd "$work_dir"
  zip -qr "$output" "smh-portal-development"
)
sha256sum "$output"
printf 'Packaged Development release: %s\n' "$output"
