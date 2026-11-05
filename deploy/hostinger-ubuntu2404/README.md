# Smart Money Hub VPS transfer

This directory contains the systemd service and a blank environment-file template
for the Hostinger Ubuntu 24.04 VPS.

## Transfer bundle contents

The migration archive should contain:

- `smart_money_hub_bot/` — bot source, including the current admin status fix
- `attached_assets/` — owner-provided diagrams and course assets
- `data/smart_money_hub.sqlite3` — a consistent SQLite backup of the current bot
- `deploy/hostinger-ubuntu2404/` — this guide and service template

It must not contain credentials. Add the Telegram token, admin ID, and Gemini key
directly to `/etc/smart-money-hub.env` on the VPS, then restrict that file to root.

## Runtime layout on the VPS

- App source: `/opt/smart-money-hub/app`
- Python 3.13: `/opt/smart-money-hub/python`
- Virtual environment: `/opt/smart-money-hub/.venv`
- Persistent database: `/opt/smart-money-hub/data/smart_money_hub.sqlite3`
- Environment file: `/etc/smart-money-hub.env`
- systemd unit: `/etc/systemd/system/smart-money-hub.service`

The bot uses Python's standard library and SQLite; no pip packages are required.
The database directory must be writable by the `smhbot` service account. Source
and image assets may remain read-only to that account.

## Safe cutover

Keep the Replit process running while preparing and checking the VPS. Use a
separate Telegram test bot and an empty test database for the initial service
test. Do not run the production Telegram token on both hosts: this bot uses long
polling, and only one active poller should use that token.

Before cutover, confirm the database backup is installed at the path above and
the production environment settings match Replit. Stop the Replit workflow before
starting the VPS service with the production token. If anything fails, stop the
VPS service before restarting the Replit workflow.
