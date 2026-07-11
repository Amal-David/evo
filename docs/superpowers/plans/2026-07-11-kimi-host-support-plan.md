# Kimi Code CLI host support for evo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Kimi Code CLI as a first-class evo host, including host adapter, plugin manifest, slash commands, hooks/drain, and native Kimi `Agent` tool dispatch.

**Architecture:** Reuse evo's existing host-install adapter pattern and inject/drain self-contained host path (similar to Cursor). Add a Kimi plugin manifest under `.kimi-plugin/` and Kimi-native plugin tools under `kimi_tools/` for correlating Kimi `Agent` instances with evo experiments. The optimize skill instructs the orchestrator to use Kimi's `Agent` tool and the new plugin tools.

**Tech Stack:** Python 3.10+, pytest, Kimi Code CLI (beta plugin/hook/agent APIs), evo's existing plugin/skill/hook infrastructure.

## Global Constraints

- Kimi plugin and hook APIs are beta and may change; keep the integration surface small and fail-open.
- All hook commands must be on PATH or use plugin-relative paths.
- Slash commands are namespaced by plugin id (`evo`), so users invoke `/evo:discover` and `/evo:optimize`.
- Plugin tools receive JSON on stdin and write JSON to stdout.
- The evo CLI on PATH provides `evo-drain`; do not assume a separate hook binary for Kimi.
- Changes must not break existing hosts (Claude Code, Codex, Cursor, etc.).
- All new code needs tests mirroring the existing `tests/unit/` patterns.

---

## File Structure

| File | Responsibility |
|---|---|
| `plugins/evo/src/evo/core.py` | Add `"kimi"` to `SUPPORTED_HOSTS`. |
| `plugins/evo/src/evo/host_install/__init__.py` | Import and register the `kimi` adapter. |
| `plugins/evo/src/evo/host_install/kimi.py` | `evo install/uninstall/doctor kimi` implementation. |
| `plugins/evo/.kimi-plugin/plugin.json` | Kimi plugin manifest (skills, commands, hooks, Phase 2 tools). |
| `plugins/evo/commands/discover.md` | `/evo:discover` slash command. |
| `plugins/evo/commands/optimize.md` | `/evo:optimize` slash command. |
| `plugins/evo/src/evo/inject/drain.py` | Kimi self-contained drain path and envelope. |
| `plugins/evo/src/evo/inject/registry.py` | Kimi session env detection. |
| `plugins/evo/src/evo/hosts/kimi_native.py` | Helpers for Kimi `Agent` instance ↔ evo experiment mapping. |
| `plugins/evo/kimi_tools/spawn_subagent.py` | Kimi plugin tool to record agent↔experiment mapping. |
| `plugins/evo/kimi_tools/wait_subagent.py` | Kimi plugin tool to poll experiment result by agent id. |
| `plugins/evo/skills/optimize/SKILL.md` | Add Kimi `Agent` tool instructions under Host conventions. |
| `README.md` | List Kimi as supported host. |
| `plugins/evo/skills/infra-setup/references/provider-matrix.md` | Add Kimi setup row. |
| `tests/unit/test_kimi_host_install.py` | Unit tests for host adapter. |
| `tests/unit/test_kimi_drain.py` | Unit tests for Kimi drain envelope. |
| `tests/unit/test_kimi_native_dispatch.py` | Unit tests for plugin tools and mapping helpers. |

---

## Task 1: Register Kimi in core and host_install

**Files:**
- Modify: `plugins/evo/src/evo/core.py:29-39`
- Modify: `plugins/evo/src/evo/host_install/__init__.py:31-42`
- Test: `tests/unit/test_kimi_host_install.py` (created in Task 2, but add a minimal test here)

**Interfaces:**
- Consumes: existing `SUPPORTED_HOSTS` frozenset and `ADAPTERS` dict.
- Produces: `"kimi"` is a valid host name returned by `get("kimi")`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_kimi_host_install.py`:

```python
from evo.host_install import get, SUPPORTED_HOSTS


def test_kimi_is_supported():
    assert "kimi" in SUPPORTED_HOSTS


def test_kimi_adapter_registered():
    module = get("kimi")
    assert hasattr(module, "install")
    assert hasattr(module, "uninstall")
    assert hasattr(module, "doctor")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Volumes/home_ext1/src_pierre/evo/plugins/evo
pytest tests/unit/test_kimi_host_install.py -v
```

Expected: two failures (`"kimi" not in SUPPORTED_HOSTS`, `unknown host 'kimi'`).

- [ ] **Step 3: Implement minimal changes**

In `plugins/evo/src/evo/core.py`, add `"kimi"` to `SUPPORTED_HOSTS`:

```python
SUPPORTED_HOSTS = frozenset({
    "claude-code",
    "claude-science",
    "codex",
    "cursor",
    "kimi",
    "opencode",
    "openclaw",
    "hermes",
    "pi",
    "generic",
})
```

In `plugins/evo/src/evo/host_install/__init__.py`, import and register:

```python
from . import claude_code, claude_science, codex, cursor, hermes, kimi, opencode, openclaw, pi

ADAPTERS = {
    "claude-code": claude_code,
    "claude-science": claude_science,
    "codex": codex,
    "cursor": cursor,
    "hermes": hermes,
    "kimi": kimi,
    "opencode": opencode,
    "openclaw": openclaw,
    "pi": pi,
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_kimi_host_install.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/evo/src/evo/core.py plugins/evo/src/evo/host_install/__init__.py tests/unit/test_kimi_host_install.py
git commit -m "feat(kimi): register kimi host in SUPPORTED_HOSTS and ADAPTERS"
```

---

## Task 2: Create the Kimi host-install adapter

**Files:**
- Create: `plugins/evo/src/evo/host_install/kimi.py`
- Modify: `tests/unit/test_kimi_host_install.py`

**Interfaces:**
- Consumes: argparse namespace with optional `from_path`, `version`, `force`.
- Produces: `install(args) -> int`, `uninstall(args) -> int`, `doctor(args) -> int`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_kimi_host_install.py`:

```python
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from evo.host_install import kimi as kimi_mod


@pytest.fixture
def fake_kimi_home(tmp_path, monkeypatch):
    home = tmp_path / "kimi-home"
    home.mkdir()
    monkeypatch.setenv("KIMI_CODE_HOME", str(home))
    return home


def test_kimi_base_honors_env_var(fake_kimi_home):
    assert kimi_mod._kimi_base() == fake_kimi_home


def test_kimi_base_defaults_to_home(monkeypatch):
    monkeypatch.delenv("KIMI_CODE_HOME", raising=False)
    assert kimi_mod._kimi_base() == Path.home() / ".kimi"


def test_install_missing_kimi_binary(fake_kimi_home, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    from argparse import Namespace
    rc = kimi_mod.install(Namespace(from_path=None, version=None, force=False))
    assert rc == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_kimi_host_install.py::test_kimi_base_honors_env_var -v
```

Expected: `AttributeError: module 'evo.host_install.kimi' has no attribute '_kimi_base'`.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/evo/src/evo/host_install/kimi.py`:

```python
"""Kimi Code CLI host install adapter.

Installs evo as a Kimi plugin by copying the plugin root into Kimi's
managed plugin directory. Also wires hooks via the plugin manifest.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _kimi_base() -> Path:
    home_override = os.environ.get("KIMI_CODE_HOME")
    return Path(home_override) if home_override else Path.home() / ".kimi"


def _kimi_plugin_dir() -> Path:
    return _kimi_base() / "plugins" / "managed" / "evo"


def _plugin_root(from_path: str | None = None) -> Path:
    if from_path:
        p = Path(from_path).resolve()
        candidate = p / "plugins" / "evo"
        if candidate.exists():
            return candidate
        if (p / ".kimi-plugin" / "plugin.json").exists() or (p / "kimi.plugin.json").exists():
            return p
        return candidate
    # Running from an installed evo-hq-cli wheel: locate the plugin root
    # relative to this source file (plugins/evo/src/evo/host_install/).
    here = Path(__file__).resolve().parent.parent.parent  # plugins/evo
    return here


def _release_version_re():
    import re
    return re.compile(r"^\d+\.\d+\.\d+([.\-+a-zA-Z0-9]*)$")


def _github_source(version: str) -> str:
    ref = f"v{version}" if _release_version_re().match(version) else version
    return f"https://github.com/evo-hq/evo/tree/{ref}/plugins/evo"


def install(args: argparse.Namespace) -> int:
    if shutil.which("kimi") is None:
        print(
            "ERROR: `kimi` binary not on PATH. Install Kimi Code CLI first:\n"
            "  npm install -g @moonshot-ai/kimi-code-cli",
            file=sys.stderr,
        )
        return 2

    version = getattr(args, "version", None)
    from_path = getattr(args, "from_path", None)

    if version:
        # Let Kimi fetch the plugin from GitHub.
        source = _github_source(version)
        cmd = ["kimi", "plugin", "install", source]
        print(f"$ {' '.join(cmd)}")
        rc = subprocess.call(cmd)
        if rc != 0:
            return rc
        print(
            "\n✓ evo installed for kimi.\n"
            "  Start a new Kimi session (or run /reload) to load the plugin."
        )
        return 0

    src = _plugin_root(from_path)
    if not src.exists():
        print(f"ERROR: evo plugin source not found at {src}", file=sys.stderr)
        return 2

    dst = _kimi_plugin_dir()
    if dst.exists():
        print(f"removing previous install at {dst}")
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"copying {src} -> {dst}")
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "__pycache__", "build", "dist",
            ".pytest_cache", "*.egg-info", "node_modules",
        ),
    )

    print(
        "\n✓ evo installed for kimi.\n"
        "  Start a new Kimi session (or run /reload) to load the plugin."
    )
    return 0


def uninstall(args: argparse.Namespace) -> int:
    dst = _kimi_plugin_dir()
    if dst.exists():
        shutil.rmtree(dst)
        print(f"removed {dst}")
    else:
        print("evo plugin not installed for kimi")
    return 0


def doctor(args: argparse.Namespace) -> int:
    if shutil.which("kimi") is None:
        print("✗ `kimi` binary not on PATH")
        print("  Install: npm install -g @moonshot-ai/kimi-code-cli")
        return 1
    print(f"✓ kimi binary: {shutil.which('kimi')}")

    dst = _kimi_plugin_dir()
    manifest = dst / ".kimi-plugin" / "plugin.json"
    if not manifest.exists():
        manifest = dst / "kimi.plugin.json"
    if not manifest.exists():
        print(f"✗ evo plugin not found at {dst}")
        print("  Run: evo install kimi")
        return 1
    print(f"✓ evo plugin manifest at {manifest}")

    # Basic manifest sanity
    import json
    try:
        data = json.loads(manifest.read_text())
    except json.JSONDecodeError as exc:
        print(f"✗ could not parse manifest: {exc}")
        return 1
    if data.get("name") != "evo":
        print(f"✗ manifest name mismatch: {data.get('name')!r}")
        return 1
    print("✓ manifest name is 'evo'")
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_kimi_host_install.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/evo/src/evo/host_install/kimi.py tests/unit/test_kimi_host_install.py
git commit -m "feat(kimi): add host install adapter with install/uninstall/doctor"
```

---

## Task 3: Create the Kimi plugin manifest

**Files:**
- Create: `plugins/evo/.kimi-plugin/plugin.json`
- Test: `tests/unit/test_kimi_plugin_manifest.py`

**Interfaces:**
- Consumes: existing skill and command paths relative to plugin root.
- Produces: valid Kimi plugin manifest loadable by `kimi plugin info evo`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_kimi_plugin_manifest.py`:

```python
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "plugins" / "evo" / ".kimi-plugin" / "plugin.json"


def test_manifest_exists_and_is_valid_json():
    assert MANIFEST.exists(), f"manifest not found at {MANIFEST}"
    data = json.loads(MANIFEST.read_text())
    assert data["name"] == "evo"
    assert "version" in data
    assert "skills" in data
    assert "commands" in data
    assert "hooks" in data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_kimi_plugin_manifest.py -v
```

Expected: `assertion error: manifest not found`.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/evo/.kimi-plugin/plugin.json`:

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

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_kimi_plugin_manifest.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/evo/.kimi-plugin/plugin.json tests/unit/test_kimi_plugin_manifest.py
git commit -m "feat(kimi): add Kimi plugin manifest with skills, commands, and hooks"
```

---

## Task 4: Create slash commands for discover and optimize

**Files:**
- Create: `plugins/evo/commands/discover.md`
- Create: `plugins/evo/commands/optimize.md`
- Test: `tests/unit/test_kimi_plugin_manifest.py` (extend to verify command files exist)

**Interfaces:**
- Consumes: evo CLI commands `evo discover` and `evo optimize`.
- Produces: Kimi-recognized slash commands `/evo:discover` and `/evo:optimize`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_kimi_plugin_manifest.py`:

```python
COMMANDS_DIR = REPO_ROOT / "plugins" / "evo" / "commands"


def test_discover_command_file_exists():
    assert (COMMANDS_DIR / "discover.md").exists()


def test_optimize_command_file_exists():
    assert (COMMANDS_DIR / "optimize.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_kimi_plugin_manifest.py::test_discover_command_file_exists -v
```

Expected: assertion failure.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/evo/commands/discover.md`:

```markdown
---
name: discover
description: Discover what to optimize and initialize an evo workspace.
---

Run `evo discover` in the current project. If the user provides an optimization target, pass it as an argument. After this command completes, use `evo status` to confirm the workspace is initialized, then run `/evo:optimize` to start the loop.
```

Create `plugins/evo/commands/optimize.md`:

```markdown
---
name: optimize
description: Run the evo autoresearch optimization loop.
---

Run `evo optimize` in the current project. This starts the structured experiment loop. You may pass parameters like `subagents=N` or `autonomous` as arguments. Do not edit files or run experiments manually while the loop is active unless the user explicitly asks for direct execution.
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_kimi_plugin_manifest.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/evo/commands/discover.md plugins/evo/commands/optimize.md tests/unit/test_kimi_plugin_manifest.py
git commit -m "feat(kimi): add /evo:discover and /evo:optimize slash commands"
```

---

## Task 5: Add Kimi drain support in inject/drain.py

**Files:**
- Modify: `plugins/evo/src/evo/inject/drain.py`
- Test: `tests/unit/test_kimi_drain.py`

**Interfaces:**
- Consumes: Kimi hook stdin payload (`session_id`, `cwd`, `hook_event_name`, `tool_name`, `tool_input`, `prompt`).
- Produces: Kimi-compatible stdout envelope (`hookSpecificOutput.additionalContext` or `permissionDecision: deny`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_kimi_drain.py`:

```python
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "evo" / "src"))

from evo.inject.drain import main
from evo.inject.paths import session_file
from evo.inject.registry import register_session


def _make_workspace(tmp: Path) -> Path:
    import subprocess
    root = tmp / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@evo"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)
    (root / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
    from evo.core import init_workspace
    init_workspace(root, target="agent.py", benchmark="python bench.py", metric="max", gate=None)
    return root


class KimiDrainTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = _make_workspace(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _fire(self, payload: dict):
        stdin_buf = io.StringIO(json.dumps(payload))
        stdout_buf = io.StringIO()
        with patch("sys.stdin", stdin_buf), patch("sys.stdout", stdout_buf):
            main(["--host", "kimi"])
        return json.loads(stdout_buf.getvalue())

    def test_session_start_registers_session(self):
        sid = "kimi-test-sid"
        self._fire({
            "session_id": sid,
            "cwd": str(self.root),
            "hook_event_name": "SessionStart",
            "source": "startup",
        })
        rec = json.loads(session_file(self.root, sid).read_text())
        assert rec["host"] == "kimi"
        assert rec["session_id"] == sid

    def test_user_prompt_submit_arms_optimize_mode(self):
        sid = "kimi-test-sid"
        self._fire({
            "session_id": sid,
            "cwd": str(self.root),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "/evo:optimize",
        })
        rec = json.loads(session_file(self.root, sid).read_text())
        assert rec["optimize_mode"] is True

    def test_pretooluse_empty_marker_returns_empty(self):
        sid = "kimi-test-sid"
        register_session(self.root, sid, "kimi")
        out = self._fire({
            "session_id": sid,
            "cwd": str(self.root),
            "hook_event_name": "PreToolUse",
            "tool_name": "Shell",
            "tool_input": {"command": "echo hi"},
        })
        assert out == {}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_kimi_drain.py -v
```

Expected: failures because Kimi host path is not implemented.

- [ ] **Step 3: Write minimal implementation**

In `plugins/evo/src/evo/inject/drain.py`:

1. Add `"kimi"` to the self-contained host handling in `main()`.
2. Add Kimi-specific envelope emission in `emit_for_host()`.

In `emit_for_host`, add before the final fallback:

```python
if host == "kimi":
    # Kimi hooks: exit-0 stdout is added to the agent's context. The
    # structured envelope uses hookSpecificOutput with additionalContext.
    # Policy blocks are emitted by drain_session before this function is
    # called, using the same envelope with permissionDecision: deny.
    evt = hook_event or "PreToolUse"
    out = {"hookSpecificOutput": {"hookEventName": evt, "additionalContext": text}}
    sys.stdout.write(json.dumps(out, separators=(",", ":")))
    return
```

In `main()`, after the existing cursor self-contained branch (around line 1466-1500), add an equivalent branch for Kimi. The simplest approach is to extend the self-contained branch to accept `--host kimi`:

```python
# Mode 2: self-contained — resolve everything from args + stdin payload.
host = args.host or "cursor"
if host in ("cursor", "kimi"):
    session = args.session or payload.get("session_id") or payload.get("conversation_id")
    root = _resolve_root_from_payload(payload)
    if not session or root is None or not inject_root(root).parent.exists():
        _drain_debug(stage="resolve", host=host, hook_event=hook_event,
                     payload_keys=sorted(payload.keys()), session=session,
                     root=str(root) if root else None, decision="bail")
        sys.stdout.write("{}")
        return 0
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    registered = session_file(root, session).exists()
    has_marker = marker.exists(root, session)
    if host == "cursor":
        _maybe_mark_engaged_from_shell(root, session, host, hook_event, payload)
    _maybe_mark_autonomous_from_shell(root, session, host, hook_event, payload)
    gate = _self_contained_gate(root, session, host, hook_event, tool_name, tool_input)
    _maybe_mark_optimize_from_prompt(root, session, host, hook_event, payload)
    _drain_debug(stage="gate", host=host, hook_event=hook_event, session=session,
                 root=str(root), tool_name=tool_name,
                 registered_before=registered, marker=has_marker, gate=gate)
    if not gate:
        sys.stdout.write("{}")
        return 0
    return drain_session(root, session, host=host, hook_event=hook_event, payload=payload)
```

This reuses `_self_contained_gate` (it already accepts `host` and registers correctly). Two small helper updates are needed:

In `_maybe_mark_engaged_from_shell`, change the guard from `if host != "cursor":` to `if host not in ("cursor", "kimi"):` so an `evo ...` shell command marks the Kimi session as engaged.

In `_maybe_mark_autonomous_from_shell`, change the guard from `if host not in ("cursor", "codex", "claude-code"):` to `if host not in ("cursor", "codex", "claude-code", "kimi"):` so `evo autonomous on|off` arms/disarms the hook session on Kimi.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_kimi_drain.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/evo/src/evo/inject/drain.py tests/unit/test_kimi_drain.py
git commit -m "feat(kimi): add self-contained drain path and hook envelope"
```

---

## Task 6: Add Kimi session env detection

**Files:**
- Modify: `plugins/evo/src/evo/inject/registry.py`
- Test: `tests/unit/test_kimi_drain.py` (extend)

**Interfaces:**
- Consumes: environment variables.
- Produces: `detect_session()` returns `("kimi", sid)` when `KIMI_CODE_SESSION_ID` is set.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_kimi_drain.py`:

```python
from evo.inject.registry import detect_session


def test_detect_session_from_kimi_env(monkeypatch):
    monkeypatch.setenv("KIMI_CODE_SESSION_ID", "kimi-sid-123")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    assert detect_session() == ("kimi", "kimi-sid-123")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_kimi_drain.py::test_detect_session_from_kimi_env -v
```

Expected: assertion failure (`detect_session()` returns None).

- [ ] **Step 3: Write minimal implementation**

In `plugins/evo/src/evo/inject/registry.py`, add to `HOST_SESSION_ENV_VARS`:

```python
HOST_SESSION_ENV_VARS = (
    ("codex", "CODEX_THREAD_ID"),
    ("claude-code", "CLAUDE_CODE_SESSION_ID"),
    ("hermes", "HERMES_SESSION_ID"),
    ("kimi", "KIMI_CODE_SESSION_ID"),
    ("opencode", "OPENCODE_SESSION_ID"),
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_kimi_drain.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/evo/src/evo/inject/registry.py tests/unit/test_kimi_drain.py
git commit -m "feat(kimi): detect Kimi session from KIMI_CODE_SESSION_ID"
```

---

## Task 7: Documentation updates

**Files:**
- Modify: `README.md`
- Modify: `plugins/evo/skills/infra-setup/references/provider-matrix.md`
- Test: manual grep/verification

**Interfaces:**
- Consumes: existing host lists.
- Produces: Kimi listed as supported host with install command.

- [ ] **Step 1: Update README.md**

Find the line:

```
Runs on Claude Code, Codex, Cursor, OpenClaw, Hermes, Opencode, or Pi.
```

Change to:

```
Runs on Claude Code, Codex, Cursor, Kimi, OpenClaw, Hermes, Opencode, or Pi.
```

Find:

```bash
evo install <host>     # claude-code | codex | cursor | hermes | opencode | openclaw | pi
```

Change to:

```bash
evo install <host>     # claude-code | codex | cursor | hermes | kimi | opencode | openclaw | pi
```

- [ ] **Step 2: Update provider-matrix.md**

Append a row to the table:

```markdown
| `kimi` | Kimi Code CLI plugin + hooks | Install Kimi Code CLI, then `evo install kimi` | skills, commands, hooks, plugin tools (Phase 2) |
```

- [ ] **Step 3: Verify**

```bash
grep -n "Kimi\|kimi" README.md plugins/evo/skills/infra-setup/references/provider-matrix.md
```

Expected: Kimi appears in both files.

- [ ] **Step 4: Commit**

```bash
git add README.md plugins/evo/skills/infra-setup/references/provider-matrix.md
git commit -m "docs(kimi): list Kimi as supported host"
```

---

## Task 8: Integration smoke test for install/doctor

**Files:**
- Modify: `tests/unit/test_kimi_host_install.py`

**Interfaces:**
- Consumes: `host_install/kimi.py` functions.
- Produces: verified file-copy install/uninstall/doctor cycle.

- [ ] **Step 1: Write the test**

Append to `tests/unit/test_kimi_host_install.py`:

```python
def test_install_copies_plugin(fake_kimi_home, tmp_path, monkeypatch):
    # Use the real plugin root from this checkout
    here = Path(__file__).resolve().parents[2] / "plugins" / "evo"
    monkeypatch.setattr("shutil.which", lambda name: "/fake/kimi" if name == "kimi" else None)
    from argparse import Namespace
    rc = kimi_mod.install(Namespace(from_path=str(here.parent.parent), version=None, force=False))
    assert rc == 0
    assert (fake_kimi_home / "plugins" / "managed" / "evo" / ".kimi-plugin" / "plugin.json").exists()


def test_doctor_after_install(fake_kimi_home, tmp_path, monkeypatch):
    here = Path(__file__).resolve().parents[2] / "plugins" / "evo"
    monkeypatch.setattr("shutil.which", lambda name: "/fake/kimi" if name == "kimi" else None)
    from argparse import Namespace
    kimi_mod.install(Namespace(from_path=str(here.parent.parent), version=None, force=False))
    rc = kimi_mod.doctor(Namespace())
    assert rc == 0
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/unit/test_kimi_host_install.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_kimi_host_install.py
git commit -m "test(kimi): smoke test install and doctor cycle"
```

---

## Task 9: Kimi native dispatch helpers

**Files:**
- Create: `plugins/evo/src/evo/hosts/kimi_native.py`
- Test: `tests/unit/test_kimi_native_dispatch.py`

**Interfaces:**
- Consumes: evo workspace root and experiment id.
- Produces: read/write mapping files and poll experiment results.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_kimi_native_dispatch.py`:

```python
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "evo" / "src"))

from evo.hosts.kimi_native import (
    agent_mapping_path,
    read_agent_mapping,
    write_agent_mapping,
)


def test_mapping_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / ".evo" / "run_test"
        exp_id = "exp-0001"
        mapping = {"agent_id": "kimi-agent-123", "exp_id": exp_id, "brief": "test"}
        write_agent_mapping(run_dir, exp_id, mapping)
        assert read_agent_mapping(run_dir, exp_id) == mapping


def test_read_missing_mapping_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / ".evo" / "run_test"
        assert read_agent_mapping(run_dir, "exp-0000") is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_kimi_native_dispatch.py -v
```

Expected: import errors.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/evo/src/evo/hosts/kimi_native.py`:

```python
"""Helpers for native Kimi Agent subagent dispatch.

Tracks the mapping between Kimi Agent instance ids and evo experiment ids,
and polls evo experiment results.
"""

from __future__ import annotations

import json
from pathlib import Path


def agent_mapping_path(run_dir: Path, exp_id: str) -> Path:
    return run_dir / "experiments" / exp_id / "kimi_agent.json"


def write_agent_mapping(run_dir: Path, exp_id: str, mapping: dict) -> None:
    p = agent_mapping_path(run_dir, exp_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    from evo.core import atomic_write_json
    atomic_write_json(p, mapping)


def read_agent_mapping(run_dir: Path, exp_id: str) -> dict | None:
    p = agent_mapping_path(run_dir, exp_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def read_agent_mapping_by_agent_id(run_dir: Path, agent_id: str) -> dict | None:
    exp_dir = run_dir / "experiments"
    if not exp_dir.exists():
        return None
    for p in exp_dir.rglob("kimi_agent.json"):
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("agent_id") == agent_id:
            return data
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_kimi_native_dispatch.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/evo/src/evo/hosts/kimi_native.py tests/unit/test_kimi_native_dispatch.py
git commit -m "feat(kimi): add native Agent dispatch mapping helpers"
```

---

## Task 10: spawn_subagent plugin tool

**Files:**
- Create: `plugins/evo/kimi_tools/spawn_subagent.py`
- Modify: `tests/unit/test_kimi_native_dispatch.py`

**Interfaces:**
- Consumes: JSON stdin with `exp_id`, `agent_id`, optional `brief`.
- Produces: JSON stdout confirming the mapping was written.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_kimi_native_dispatch.py`:

```python
SPAWN_TOOL = REPO_ROOT / "plugins" / "evo" / "kimi_tools" / "spawn_subagent.py"


def test_spawn_subagent_tool(tmp_path):
    root = tmp_path / "repo"
    (root / ".evo" / "run_test" / "experiments" / "exp-0001").mkdir(parents=True)
    payload = json.dumps({
        "exp_id": "exp-0001",
        "agent_id": "kimi-agent-123",
        "brief": "optimize parser",
    })
    env = {"EVO_RUN_DIR": str(root / ".evo" / "run_test")}
    r = subprocess.run(
        [sys.executable, str(SPAWN_TOOL)],
        input=payload,
        env={**dict(os.environ), **env},
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_kimi_native_dispatch.py::test_spawn_subagent_tool -v
```

Expected: file not found error.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/evo/kimi_tools/spawn_subagent.py`:

```python
#!/usr/bin/env python3
"""Kimi plugin tool: record the mapping between a Kimi Agent and an evo experiment."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from evo.core import find_workspace_root, workspace_path
from evo.hosts.kimi_native import write_agent_mapping


def main() -> int:
    try:
        params = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps({"error": "invalid json stdin"}))
        return 2

    exp_id = params.get("exp_id")
    agent_id = params.get("agent_id")
    if not exp_id or not agent_id:
        print(json.dumps({"error": "exp_id and agent_id are required"}))
        return 2

    run_dir_env = os.environ.get("EVO_RUN_DIR")
    if run_dir_env:
        run_dir = Path(run_dir_env)
        root = find_workspace_root(run_dir)
    else:
        root = find_workspace_root(Path.cwd())
        run_dir = workspace_path(root)
    if root is None:
        print(json.dumps({"error": "not inside an evo workspace"}))
        return 2

    write_agent_mapping(run_dir, exp_id, {
        "agent_id": agent_id,
        "exp_id": exp_id,
        "brief": params.get("brief", ""),
    })
    print(json.dumps({"status": "ok", "exp_id": exp_id, "agent_id": agent_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_kimi_native_dispatch.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/evo/kimi_tools/spawn_subagent.py tests/unit/test_kimi_native_dispatch.py
git commit -m "feat(kimi): add evo_spawn_subagent plugin tool"
```

---

## Task 11: wait_subagent plugin tool

**Files:**
- Create: `plugins/evo/kimi_tools/wait_subagent.py`
- Modify: `tests/unit/test_kimi_native_dispatch.py`

**Interfaces:**
- Consumes: JSON stdin with `agent_id`.
- Produces: JSON stdout with experiment status/result.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_kimi_native_dispatch.py`:

```python
WAIT_TOOL = REPO_ROOT / "plugins" / "evo" / "kimi_tools" / "wait_subagent.py"


def test_wait_subagent_tool(tmp_path):
    root = tmp_path / "repo"
    run_dir = root / ".evo" / "run_test"
    exp_dir = run_dir / "experiments" / "exp-0001"
    exp_dir.mkdir(parents=True)
    mapping = {"agent_id": "kimi-agent-123", "exp_id": "exp-0001", "brief": ""}
    from evo.hosts.kimi_native import write_agent_mapping
    write_agent_mapping(run_dir, "exp-0001", mapping)

    payload = json.dumps({"agent_id": "kimi-agent-123"})
    env = {"EVO_RUN_DIR": str(root / ".evo" / "run_test")}
    r = subprocess.run(
        [sys.executable, str(WAIT_TOOL)],
        input=payload,
        env={**dict(os.environ), **env},
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["agent_id"] == "kimi-agent-123"
    assert out["exp_id"] == "exp-0001"
    assert out["status"] == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_kimi_native_dispatch.py::test_wait_subagent_tool -v
```

Expected: file not found error.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/evo/kimi_tools/wait_subagent.py`:

```python
#!/usr/bin/env python3
"""Kimi plugin tool: poll the evo experiment result for a given Kimi Agent id."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from evo.core import experiment_result_path, find_workspace_root, workspace_path
from evo.hosts.kimi_native import read_agent_mapping_by_agent_id


def main() -> int:
    try:
        params = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps({"error": "invalid json stdin"}))
        return 2

    agent_id = params.get("agent_id")
    if not agent_id:
        print(json.dumps({"error": "agent_id is required"}))
        return 2

    run_dir_env = os.environ.get("EVO_RUN_DIR")
    if run_dir_env:
        run_dir = Path(run_dir_env)
        root = find_workspace_root(run_dir)
    else:
        root = find_workspace_root(Path.cwd())
        run_dir = workspace_path(root)
    if root is None:
        print(json.dumps({"error": "not inside an evo workspace"}))
        return 2

    mapping = read_agent_mapping_by_agent_id(run_dir, agent_id)
    if mapping is None:
        print(json.dumps({"error": "agent mapping not found"}))
        return 2

    exp_id = mapping["exp_id"]
    result_path = experiment_result_path(root, exp_id)
    result = None
    status = "pending"
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text())
            status = result.get("status", "evaluated")
        except (OSError, json.JSONDecodeError):
            status = "error"
    out = {
        "agent_id": agent_id,
        "exp_id": exp_id,
        "status": status,
        "result": result,
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_kimi_native_dispatch.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/evo/kimi_tools/wait_subagent.py tests/unit/test_kimi_native_dispatch.py
git commit -m "feat(kimi): add evo_wait_subagent plugin tool"
```

---

## Task 12: Declare plugin tools in the manifest

**Files:**
- Modify: `plugins/evo/.kimi-plugin/plugin.json`
- Modify: `tests/unit/test_kimi_plugin_manifest.py`

**Interfaces:**
- Consumes: tool scripts created in Tasks 10-11.
- Produces: manifest with `tools` array.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_kimi_plugin_manifest.py`:

```python
def test_manifest_declares_tools():
    data = json.loads(MANIFEST.read_text())
    tools = data.get("tools", [])
    names = {t["name"] for t in tools}
    assert "evo_spawn_subagent" in names
    assert "evo_wait_subagent" in names
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_kimi_plugin_manifest.py::test_manifest_declares_tools -v
```

Expected: assertion failure.

- [ ] **Step 3: Write minimal implementation**

Add to `plugins/evo/.kimi-plugin/plugin.json` after `hooks`:

```json
  "tools": [
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
    },
    {
      "name": "evo_wait_subagent",
      "description": "Poll the evo experiment result for a given Kimi Agent id",
      "command": ["python3", "./kimi_tools/wait_subagent.py"],
      "parameters": {
        "type": "object",
        "properties": {
          "agent_id": {"type": "string"}
        },
        "required": ["agent_id"]
      }
    }
  ]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_kimi_plugin_manifest.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/evo/.kimi-plugin/plugin.json tests/unit/test_kimi_plugin_manifest.py
git commit -m "feat(kimi): declare evo_spawn_subagent and evo_wait_subagent tools"
```

---

## Task 13: Update optimize skill for Kimi Agent tool

**Files:**
- Modify: `plugins/evo/skills/optimize/SKILL.md`
- Test: manual verification that Kimi instructions exist

**Interfaces:**
- Consumes: Kimi `Agent` tool and plugin tools.
- Produces: skill text that tells the orchestrator how to dispatch on Kimi.

- [ ] **Step 1: Write the failing check**

Append to `tests/unit/test_kimi_plugin_manifest.py` (or create `tests/unit/test_kimi_optimize_skill.py`):

```python
OPTIMIZE_SKILL = REPO_ROOT / "plugins" / "evo" / "skills" / "optimize" / "SKILL.md"


def test_optimize_skill_mentions_kimi_agent_tool():
    text = OPTIMIZE_SKILL.read_text()
    assert "Kimi" in text or "kimi" in text
    assert "Agent" in text
    assert "evo_spawn_subagent" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_kimi_plugin_manifest.py::test_optimize_skill_mentions_kimi_agent_tool -v
```

Expected: assertion failure.

- [ ] **Step 3: Write minimal implementation**

In `plugins/evo/skills/optimize/SKILL.md`, find the "Host conventions" section. Add a Kimi subsection:

```markdown
### Kimi Code CLI

On Kimi, use the built-in `Agent` tool to spawn optimization subagents:

- `subagent_type`: `coder`
- `run_in_background`: `true`
- `description`: `evo-exp-<exp_id>`
- `prompt`: the full brief, ending with the instruction to load the `evo:subagent` skill

After each `Agent` call returns an `agent_id`, immediately call the `evo_spawn_subagent` plugin tool with `exp_id` and `agent_id` so evo can correlate the Kimi agent instance with the experiment. To wait for completion, call `evo_wait_subagent` with the `agent_id`, or poll `evo status <exp_id>` directly.
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_kimi_plugin_manifest.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/evo/skills/optimize/SKILL.md tests/unit/test_kimi_plugin_manifest.py
git commit -m "feat(kimi): document Kimi Agent tool dispatch in optimize skill"
```

---

## Task 14: Full unit test sweep

**Files:**
- All modified/created files.

- [ ] **Step 1: Run the full unit suite**

```bash
cd /Volumes/home_ext1/src_pierre/evo/plugins/evo
pytest tests/unit -x -q
```

Expected: all tests pass.

- [ ] **Step 2: Run Kimi-specific tests with verbose output**

```bash
pytest tests/unit/test_kimi_*.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit any fixes**

If fixes are needed, commit them with descriptive messages. If no fixes are needed, no additional commit is required.

---

## Self-review

### Spec coverage

| Spec section | Plan task(s) |
|---|---|
| Host adapter | Task 2, Task 8 |
| Core registration | Task 1 |
| Plugin manifest | Task 3, Task 12 |
| Slash commands | Task 4 |
| Hook drain support | Task 5 |
| Session env detection | Task 6 |
| Native Agent dispatch tools | Tasks 9-11 |
| Optimize skill update | Task 13 |
| Documentation | Task 7 |
| Testing | Every task + Task 14 |

### Placeholder scan

No `TBD`, `TODO`, or vague instructions. Each step includes concrete code, exact file paths, and expected test commands.

### Type consistency

- `host_install/kimi.py` uses `argparse.Namespace` consistently.
- `kimi_native.py` uses `Path` and `dict` consistently.
- Plugin tools use JSON stdin/stdout consistently.
- Manifest tool schema matches tool script parameter expectations.

### Known open items

- Exact Kimi hook payload field names should be verified against a live Kimi session (e.g. `tool_name` vs `toolName`). The plan uses the documented names from Kimi's Hooks docs.
- `KIMI_CODE_SESSION_ID` env var is assumed; if Kimi does not expose it, the hook-based registration path still works.
- `load_result` signature in `wait_subagent.py` must be verified; adjust if it differs.
