---
name: Trading Academy visual lessons
description: Visual and editorial requirements for member-facing market-education lessons.
---

Price-action and Smart Money Concepts lesson diagrams should use recognizable candlestick bodies and wicks rather than abstract line charts. Schematic candles must be identified as illustrative, not live market data, and lesson text must not present a pattern as a guaranteed outcome or trade instruction.

Member lessons unlock in curriculum order: completion unlocks only the next lesson. Locked lesson bodies, activities, and diagram files must stay server-protected and must not be sent to the browser before the prerequisite is complete. Do not add ad gating unless the user asks for it.

**Why:** the user wants a sequential course progression as a foundation for possible future monetization, but has not requested ads yet.

**How to apply:** enforce lesson order in API reads, progress updates, and figure delivery; preserve saved per-member progress. Use candlestick charts for price-structure examples and label all schematic figures as illustrative, not live data or trade signals.
