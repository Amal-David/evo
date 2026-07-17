---
name: discover
description: Discover what to optimize and initialize an evo workspace.
---

Load and follow the evo `discover` skill (named `discover` under the evo plugin in your skill registry — use your skill loader, not a filesystem path). It explores the repository, proposes optimization dimensions, builds the benchmark inside a baseline worktree, and runs the first experiment.

If arguments are provided below, treat them as the optimization target or focus for discovery.

$ARGUMENTS
