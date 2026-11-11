# Hostinger Development release pipeline

The manual GitHub Actions workflow
`.github/workflows/hostinger-development-release.yml` validates and packages a
Development release. It runs workspace typechecks, API tests, a Development-mode
Portal build, and an API build, then publishes a short-lived workflow artifact.

## Required GitHub configuration

Add the Development Clerk publishable key as the repository or Development
environment variable `DEV_VITE_CLERK_PUBLISHABLE_KEY`. The workflow stops before
building the frontend if that variable is absent. It contains no Clerk secret,
database credential, Telegram token, or other private key.

## Package scope and safeguards

The package contains the built Portal, built API, API runtime assets, and only
`portal-development` migrations. The API is intended to use the isolated
`smh_test` schema.

The workflow does not connect to the VPS, activate a release, apply migrations,
change Nginx, restart services, touch Production, or restart any bot. The
Development deployment must not be activated until the VPS administrator has
verified its dedicated service, API port, environment file, Nginx route,
database target, backup/rollback target, and smoke-test procedure.

Do not add root passwords or private keys to source, workflow YAML, or the
release archive. Any future VPS transfer job must use a dedicated restricted
deployment account and an administrator-installed, Development-only promotion
helper. It must not deploy to `/opt/smh-support-api/current` or affect the live
domain.
