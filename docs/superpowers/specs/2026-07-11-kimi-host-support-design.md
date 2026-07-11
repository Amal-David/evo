# Kimi Code CLI host support for evo

## Status

Approved design — awaiting implementation plan.

## Goal

Add Kimi Code CLI (Moonshot AI's open-source terminal coding agent) as a first-class evo host. Users will be able to run:

```
/evo:discover
/evo:optimize
```

inside a Kimi Code CLI session, and install/verify the integration with:

```
evo install kimi
evo doctor kimi
```

## Background

evo already supports Claude Code, Codex, Cursor, Opencode, Hermes, OpenClaw, and Pi. Each host integration consists of:

1. A host-install adapter (`plugins/evo/src/evo/host_install/<host>.py`).
2. Registration in `host_install/__init__.py` and `core.SUPPORTED_HOSTS`.
3. Host-specific plugin/skill wiring so slash commands and mid-run inject (`evo direct`) work.
4. Optional native dispatch support (only Claude Code currently has a fork-cache handler).

Kimi Code CLI exposes:

- **Agent Skills** via `SKILL.md` files.
- **Slash commands** declared in a plugin manifest.
- **Plugin tools** (executable commands with JSON-schema parameters).
- **Hooks** (beta) that receive JSON on stdin and can inject context or block tool calls.
- **Subagents** via the in-process `Agent` tool (`run_in_background`, `resume`).

There is no external CLI command to spawn Kimi subagents from outside the running Kimi session, so a traditional `evo.hosts` fork handler like `claude_fork.py` is not possible. Native Kimi dispatch must be driven from inside Kimi via its `Agent` tool.

## Scope

This design covers the full native integration (Approach 3 from the brainstorming session), implemented in two phases:

- **Phase 1:** Host adapter + plugin manifest + slash commands + hooks + drain. This makes Kimi a working evo host with skill-driven subagent dispatch.
- **Phase 2:** Kimi plugin tools + optimize skill updates for native `Agent` subagent dispatch.

Out of scope for this design:

- Publishing evo to Kimi's official marketplace (can be added later).
- Replacing evo's existing skill-driven model with a hard-coded workflow.
- Changes to remote backend providers (modal, e2b, etc.).

## Design

### Host adapter

New file: `plugins/evo/src/evo/host_install/kimi.py`

Implements `install(args)`, `uninstall(args)`, `doctor(args)`.

Responsibilities:

1. Verify the `kimi` binary is on PATH.
2. Locate or create Kimi's plugin directory (`$KIMI_CODE_HOME/plugins/managed/`).
3. Install the evo Kimi plugin by copying `plugins/evo` (the plugin root) into `$KIMI_CODE_HOME/plugins/managed/evo/`. Prefer file-copy over `kimi plugin install` for local/development installs so `--from-path` changes are reflected without re-invoking the Kimi CLI.
4. `--from-path <repo>` installs from `<repo>/plugins/evo`.
5. `--version <ref>` installs from the GitHub URL `https://github.com/evo-hq/evo/tree/<ref>/plugins/evo` so Kimi fetches the plugin subdirectory.
6. Run `kimi plugin info evo` as a sanity check.
7. `doctor` checks that the plugin is registered, the manifest is valid, and expected skills/commands/hooks are present.

### Core registration

- Add `"kimi"` to `SUPPORTED_HOSTS` in `plugins/evo/src/evo/core.py`.
- Add `kimi` adapter import and entry to `ADAPTERS` in `plugins/evo/src/evo/host_install/__init__.py`.

### Plugin manifest

New file: `plugins/evo/.kimi-plugin/plugin.json`

```json
{
  "name": "evo",
  "version": "0.7.0",
  "description": "Structured experiment-driven code optimization using tree search and parallel subagents",
  "interface": {
    "displayName": "evo",
    "shortDescription": "Autoresearch orchestrator for codebases"
  },
  "skills": "./skills",
  "commands": "./commands",
  "hooks": [
    {
      "event": "SessionStart",
      "command": "evo-drain --host kimi"
    },
    {
      "event": "UserPromptSubmit",
      "command": "evo-drain --host kimi"
    },
    {
      "event": "PreToolUse",
      "command": "evo-drain --host kimi"
    },
    {
      "event": "Stop",
      "command": "evo-drain --host kimi"
    },
    {
      "event": "SubagentStop",
      "command": "evo-drain --host kimi"
    }
  ]
}
```

Phase 2 adds a `tools` array to this manifest. Example tool declaration:

```json
{
  "name": "evo_spawn_subagent",
  "description": "Record the mapping between a Kimi Agent subagent and an evo experiment",
  "command": ["python3", "./kimi_tools/spawn_subagent.py"],
  "parameters": {
    "type": "object",
    "properties": {
      "exp_id": {"type": "string"},
      "agent_id": {"type": "string"},
      "brief": {"type": "string"}
    },
    "required": ["exp_id", "agent_id"]
  }
}
```

### Slash commands

New files:

- `plugins/evo/commands/discover.md`
- `plugins/evo/commands/optimize.md`

Each is a Markdown file with frontmatter:

```markdown
---
name: discover
description: Discover what to optimize and initialize an evo workspace.
---

Run `evo discover` in the current project. If an optimization target is provided, pass it as an argument.
```

Kimi namespaces slash commands with the plugin id, so users invoke them as `/evo:discover` and `/evo:optimize`.

### Hook drain support

Update `plugins/evo/src/evo/inject/drain.py`:

- Add `"kimi"` to the self-contained host path.
- Parse Kimi's stdin payload (`session_id`, `cwd`, `hook_event_name`, `tool_name`, `tool_input`, `prompt`).
- Resolve workspace root from `cwd` (walk up to `.evo/`).
- Register sessions on `SessionStart` / `UserPromptSubmit`.
- Arm `optimize_mode` when prompt matches `/evo:optimize`.
- Deliver queued `evo direct` directives via Kimi's `hookSpecificOutput.additionalContext` envelope.
- Policy-block denied tools via `permissionDecision: "deny"` when `optimize_mode` + `subagents_only` are armed.
- Emit stop-nudge text on `Stop` / `SubagentStop` for autonomous orchestrators.

Update `plugins/evo/src/evo/inject/registry.py`:

- Add Kimi session env detection if Kimi exposes a stable session env var (e.g. `KIMI_CODE_SESSION_ID`). If not, rely on hook-based registration.

### Phase 2: Native Agent dispatch tools

New files:

- `plugins/evo/kimi_tools/spawn_subagent.py`
- `plugins/evo/kimi_tools/wait_subagent.py`
- `plugins/evo/src/evo/hosts/kimi_native.py`

`spawn_subagent.py` is a Kimi plugin tool. It receives JSON on stdin:

```json
{
  "exp_id": "evo-exp-0001",
  "agent_id": "kimi-agent-abc123",
  "brief": "..."
}
```

It writes a mapping file under `.evo/run_XXX/experiments/<exp_id>/kimi_agent.json` so evo can correlate Kimi agent instances with experiments.

`wait_subagent.py` receives an `agent_id`, reads the mapping file under `.evo/run_XXX/experiments/<exp_id>/kimi_agent.json`, and returns the status/result from evo's experiment record for that `exp_id`.

`kimi_native.py` provides shared helpers for reading/writing the agent mapping and polling experiment results.

Update `plugins/evo/.kimi-plugin/plugin.json` to declare these tools with JSON Schema parameters.

Update `plugins/evo/skills/optimize/SKILL.md` to add a Kimi-specific subsection under "Host conventions":

- Use the `Agent` tool with `subagent_type: coder`.
- Set `run_in_background: true`.
- Use `description: evo-exp-<exp_id>`.
- Pass the brief as `prompt`.
- After spawning, call the `evo_spawn_subagent` plugin tool to record the mapping.
- To wait, call `evo_wait_subagent` or poll `evo status <exp_id>`.

### Documentation updates

- `README.md`: add Kimi to the list of supported hosts and install example.
- `plugins/evo/skills/infra-setup/references/provider-matrix.md`: add Kimi row.

## Error handling

- Hook failures are fail-open: a crashing `evo-drain` returns non-zero or emits invalid JSON, and Kimi allows the underlying tool call.
- If the `kimi` binary is missing, `evo install kimi` exits with error code 2 and a clear install hint.
- If Kimi's hook API changes (beta), degrade to plain stdout context injection.
- If the `Agent` tool is unavailable, the optimize skill falls back to orchestrator-owned sequential experiments.

## Testing

- Unit tests for `host_install/kimi.py` using a temporary `$KIMI_CODE_HOME`.
- Unit tests for `evo-drain --host kimi` payload parsing and envelope emission.
- Unit tests for `kimi_tools/spawn_subagent.py` and `wait_subagent.py` against a synthetic evo workspace.
- Smoke test: `evo install kimi --from-path <repo>` in a clean environment, then run `kimi plugin info evo` and `evo doctor kimi`.
- Optional live test: run `/evo:optimize subagents=2` in a real Kimi session against a trivial benchmark repo.

## Open questions

1. Does Kimi expose a stable session env var (e.g. `KIMI_CODE_SESSION_ID`) that subprocesses can read? If yes, we should add it to `registry.HOST_SESSION_ENV_VARS`.
2. Does Kimi's `hookSpecificOutput.additionalContext` work on `Stop` events for autonomous continuation, or do we need a different mechanism (e.g. plugin tool follow-up)?
3. Should the Kimi plugin be installed per-user (`~/.kimi/plugins/`) or can it be workspace-local? The Kimi docs currently say plugins are per-user.

These questions should be answered during implementation or via live testing, with sensible defaults chosen when ambiguous.

## Risks

- Kimi's plugin and hook systems are beta and may change. We should keep the integration surface small and version-gate where possible.
- Native Agent dispatch depends on Kimi's in-process `Agent` tool, which may not be available in all Kimi configurations.
- The skill body may need tuning after real-world use.

## References

- [Kimi Code CLI Plugins docs](https://moonshotai.github.io/kimi-cli/en/customization/plugins.html)
- [Kimi Code CLI Hooks docs](https://moonshotai.github.io/kimi-cli/en/customization/hooks.html)
- [Kimi Code CLI Agents and Subagents docs](https://moonshotai.github.io/kimi-cli/en/customization/agents.html)
