# Operations Center on the Hostinger VPS

This package serves the existing Operations Center as static files through Nginx.
Its `/api/healthz` endpoint returns the same `{ "status": "ok" }` response as the
current health route. It does not add bot telemetry, event ingestion, or content
queue integration; those dashboard sections remain unavailable as shown in the
preview.

The installer uses a separate web root and Nginx site config. It does not change
the Telegram bot service, bot credentials, Replit workflows, or DNS.

## Install the package

1. Install Nginx on the Ubuntu VPS if it is not already installed:

   ```sh
   apt update && apt install -y nginx
   ```

2. Upload and extract `smartmoneyhub-ops-vps.zip` in `/root`:

   ```sh
   cd /root
   python3 -m zipfile -e smartmoneyhub-ops-vps.zip /root/smartmoneyhub-ops-vps
   ```

3. Run the installer:

   ```sh
   bash /root/smartmoneyhub-ops-vps/deploy/hostinger-ubuntu2404/install-smartmoneyhub-ops.sh
   ```

4. Confirm the service and local responses:

   ```sh
   systemctl is-active nginx
   curl -H 'Host: smartmoneyhub.tech' http://127.0.0.1/
   curl -H 'Host: smartmoneyhub.tech' http://127.0.0.1/api/healthz
   ```

The installer backs up any existing site directory and matching Nginx config
under `/opt/smart-money-hub/ops-web-backups/`. It does not edit DNS.

## Connect the domain after local verification

The current apex A record points to Replit. Only after the site responds locally
and the VPS accepts inbound HTTP, update the apex (`@`) A record at the domain
provider to the Hostinger VPS IPv4 address. Leave mail, TXT, and unrelated DNS
records unchanged. Then verify public HTTP before requesting a certificate:

```sh
curl -I http://smartmoneyhub.tech/
```

Once the domain resolves to this VPS, install Certbot and request HTTPS:

```sh
apt install -y certbot python3-certbot-nginx
certbot --nginx -d smartmoneyhub.tech
```

Finally verify:

```sh
curl -I https://smartmoneyhub.tech/
```
