---
name: Portal auth route ordering
description: Keep public Portal login handlers reachable when multiple API subrouters share the /portal path.
---

Register public authentication endpoints before protected routes, and scope router-level session middleware to each router's own endpoint namespace rather than the shared `/portal` prefix.

**Why:** Broad `/portal` guards in earlier sibling routers returned a session-required response before the public Owner login handler could run, so correct Development credentials could never reach password verification.

**How to apply:** When adding a router under `/portal`, use its specific route prefix for authentication middleware or mount the public auth router before any broad protected router. Add a regression test for unauthenticated POST `/portal/auth/login`.
