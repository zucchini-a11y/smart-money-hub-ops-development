---
name: Google Gemini docs access
description: Workspace-specific fallback when Replit's documentation callbacks cannot fetch Google's Gemini API docs.
---

In this workspace, the registered web-search and web-fetch callbacks returned HTTP 402 for `ai.google.dev`, while direct HTTPS fetches to Google's official Gemini documentation succeeded.

**Why:** Model availability and pricing needed current verification, and the callback path failed despite the public Google docs being reachable directly.

**How to apply:** If the callbacks return 402 again, try a direct request to the exact official `ai.google.dev` documentation URL before treating the docs as unavailable.
