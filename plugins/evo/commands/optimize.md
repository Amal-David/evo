---
name: optimize
description: Run the evo autoresearch optimization loop.
---

Load and follow the evo `optimize` skill (named `optimize` under the evo plugin in your skill registry — use your skill loader, not a filesystem path). It drives the structured experiment loop: the orchestrator writes briefs and spawns subagents that own the candidate edits and runs.

Any arguments below are parameters for that skill (e.g. `subagents=N`, `budget=N`, `autonomous`).

$ARGUMENTS
