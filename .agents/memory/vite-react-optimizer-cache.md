---
name: Vite React optimizer cache
description: Diagnose stale optimized React dependencies after package versions are aligned.
---

If the browser reports a React/React DOM version mismatch while the package manifest and pnpm resolution agree, inspect the artifact's Vite optimizer metadata and clear only that artifact's generated `.vite` cache before restarting its web workflow.

**Why:** Vite can keep serving a pre-update optimized bundle after package versions have been aligned, so a restart alone may not fix the runtime mismatch.

**How to apply:** Confirm the resolved package versions first; if they match, remove the affected artifact's generated `node_modules/.vite` cache, restart its workflow, and verify the browser console.
