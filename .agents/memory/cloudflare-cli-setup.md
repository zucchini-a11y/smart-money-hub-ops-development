---
name: Cloudflare CLI setup
description: Replit-specific setup notes for Cloudflare agent skills and the official CLI.
---

In this pnpm workspace, the Replit language-package installer routes Node packages through `pnpm add` at the workspace root, which rejects the install unless explicitly made a workspace dependency. The Cloudflare `cf` CLI is a global tool, so use Cloudflare's documented global npm install rather than adding it to the bot's project dependencies. The package installer may also touch `.replit`; if cleanup is necessary, use Replit's validated `.replit` replacement flow instead of direct edits.

**Why:** A failed package install unexpectedly changed Replit configuration, while a global CLI install left application dependencies and workflows untouched.

**How to apply:** For Cloudflare CLI setup on this workspace, check Node.js >=22.18, install `cf` globally after user approval, verify `cf --version`, and never run `cf auth login` without separate authorization.
