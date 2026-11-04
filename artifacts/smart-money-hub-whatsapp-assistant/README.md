# Smart Money Hub WhatsApp Assistant

This is a separate Python 3.13 + React app. It does not import or change the Telegram bot. The WhatsApp backend uses FastAPI, SQLite, Meta's official WhatsApp Cloud API, and the existing Gemini free-tier configuration.

## Safety defaults

- Outbound messages are permanently locked to test mode in this build.
- The app sends only replies in an existing conversation, never broadcasts or starts a conversation.
- Every outbound recipient must be listed in `WHATSAPP_TEST_RECIPIENTS`.
- Admin replies are blocked when WhatsApp's 24-hour customer-service window is closed.
- No live business number or production recipient should be configured for this test.
- Meta webhook requests are checked with the app-secret signature; duplicate message IDs are ignored.
- Gemini receives message text and up to six recent exchanges for context, but not the sender's phone number or WhatsApp IDs.
- The assistant uses the existing fixed model `gemini-3.5-flash-lite`; it does not switch models. When Gemini is unavailable, it uses the saved educational notes or says it cannot answer.

## Replit Secrets for an isolated Meta test app

Do not paste these values into chat, source files, logs, or the dashboard:

- `WHATSAPP_ACCESS_TOKEN` — temporary token from the Meta test app.
- `WHATSAPP_PHONE_NUMBER_ID` — the test phone-number ID shown by Meta.
- `WHATSAPP_APP_SECRET` — app secret for webhook signature verification.
- `WHATSAPP_VERIFY_TOKEN` — a random verification phrase; enter the same value in Meta's webhook setup.
- `WHATSAPP_ADMIN_PASSWORD` — a strong password for this private dashboard.
- `WHATSAPP_TEST_RECIPIENTS` — only phone numbers that Meta explicitly lists as allowed test recipients, comma-separated.
- Optional `WHATSAPP_SESSION_SECRET` — if omitted, the app uses the existing Replit `SESSION_SECRET`.

The app uses Graph API `v25.0` by default. This can be changed with `WHATSAPP_GRAPH_API_VERSION` if Meta's official version support changes.

## Safe test sequence

1. In Meta for Developers, create or select a separate WhatsApp test app and use only its test sender number. Do not add or connect the real business number.
2. Add your own number as a permitted test recipient in Meta. Put only that same test recipient in `WHATSAPP_TEST_RECIPIENTS`.
3. Add the test values above using Replit's Secrets panel. Do not add live business credentials.
4. Start the `artifacts/smart-money-hub-whatsapp-assistant: api` and `artifacts/smart-money-hub-whatsapp-assistant: web` workflows.
5. Open the assistant preview and sign in with `WHATSAPP_ADMIN_PASSWORD`.
6. Copy the webhook URL displayed in Settings. In Meta's test app, use that HTTPS URL and the same `WHATSAPP_VERIFY_TOKEN`, then subscribe to the `messages` webhook field.
7. Send a text message from the approved test recipient to Meta's test sender. Confirm the conversation appears in the dashboard and the assistant reply is visible.
8. Confirm a number not listed in `WHATSAPP_TEST_RECIPIENTS` is blocked, and confirm the Pause control stops assistant replies.

Meta's test setup and permissions can change. Follow the current official guides:

- [WhatsApp Cloud API getting started](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)
- [WhatsApp Cloud API webhook setup](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks)
- [Meta Graph API changelog](https://developers.facebook.com/docs/graph-api/changelog/)

This app has not been connected to a Meta account or tested with a real Meta test sender. The preview can be built and verified locally without adding credentials; end-to-end messaging remains disabled until the isolated test app is configured.
