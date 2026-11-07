# Website support Production rollback

This is a non-destructive rollback procedure. It deliberately does not drop widget tables or delete conversations/messages.

1. Set `WEBSITE_SUPPORT_ENABLED=false` in the protected API environment.
2. Restart the API service using the VPS administrator's approved release process.
3. Roll the API and landing page back to their previous release versions if required.
4. Run `nginx -t`; reload Nginx only if its configuration changed.
5. Verify `/`, `/login`, `/operations`, `/api/healthz`, and confirm `/api/public-support/availability` is disabled.
6. Preserve all `smh.website_support_*` tables and records. Reconcile or repair them only through a separately reviewed migration.

The forward migration creates only new website-support tables. Removing those tables would permanently delete support history and is not part of rollback. Do not run `DROP TABLE`, `TRUNCATE`, or a restore that would overwrite newer data as a routine rollback.

Before applying the forward migration, the administrator must back up the Production database and test the migration on a schema-only copy. If schema rollback is specifically required before any support data exists, prepare and approve a separate destructive rollback with explicit owner consent and a verified backup.
