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
from evo.inject.registry import (
    HOST_SESSION_ENV_VARS,
    detect_session,
    mark_autonomous,
    mark_optimize_mode,
    mark_subagents_only,
    register_session,
)


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

    def test_stop_event_in_optimize_autonomous_emits_nudge(self):
        sid = "kimi-test-sid"
        register_session(self.root, sid, "kimi")
        mark_optimize_mode(self.root, sid)
        mark_autonomous(self.root, sid)
        out = self._fire({
            "session_id": sid,
            "cwd": str(self.root),
            "hook_event_name": "Stop",
        })
        # Kimi only surfaces a hook's text when the hook BLOCKS: on Stop it
        # appends permissionDecisionReason to the context and continues. A
        # non-block result is reduced to {action:"allow"} and its message is
        # discarded, so the nudge must ride the deny envelope.
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "[EVO LOOP]" in out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_pretooluse_non_shell_defers_for_kimi(self):
        sid = "kimi-test-sid"
        register_session(self.root, sid, "kimi")
        out = self._fire({
            "session_id": sid,
            "cwd": str(self.root),
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"path": "agent.py"},
        })
        assert out == {}

    def test_pretooluse_shell_evo_marks_engaged_for_kimi(self):
        sid = "kimi-test-sid"
        register_session(self.root, sid, "kimi")
        out = self._fire({
            "session_id": sid,
            "cwd": str(self.root),
            "hook_event_name": "PreToolUse",
            "tool_name": "Shell",
            "tool_input": {"command": "evo direct hello"},
        })
        assert out == {}
        rec = json.loads(session_file(self.root, sid).read_text())
        assert rec.get("has_evo_engaged") is True
        assert rec.get("engaged_at")

    def _queue_directive(self, sid: str) -> None:
        from evo.inject import marker, queue
        queue.append_workspace_event(self.root, "hello from evo")
        marker.touch(self.root, sid)

    def test_pretooluse_shell_does_not_consume_directive_on_kimi(self):
        """Cursor delivers mid-turn on shell via an updated_input echo. Kimi
        has no such channel — a block here would deny the tool — so the
        directive must wait for Stop rather than be consumed and lost."""
        sid = "kimi-test-sid"
        register_session(self.root, sid, "kimi")
        self._queue_directive(sid)
        out = self._fire({
            "session_id": sid,
            "cwd": str(self.root),
            "hook_event_name": "PreToolUse",
            "tool_name": "Shell",
            "tool_input": {"command": "ls"},
        })
        assert out == {}
        from evo.inject import marker
        assert marker.exists(self.root, sid), "directive was consumed without delivery"

    def test_subagent_stop_does_not_consume_directive_on_kimi(self):
        """Kimi fires SubagentStop fire-and-forget and discards the result,
        so a directive drained there would vanish."""
        sid = "kimi-test-sid"
        register_session(self.root, sid, "kimi")
        self._queue_directive(sid)
        out = self._fire({
            "session_id": sid,
            "cwd": str(self.root),
            "hook_event_name": "SubagentStop",
        })
        assert out == {}
        from evo.inject import marker
        assert marker.exists(self.root, sid), "directive was consumed without delivery"

    def test_stop_delivers_directive_via_block_envelope_on_kimi(self):
        sid = "kimi-test-sid"
        register_session(self.root, sid, "kimi")
        self._queue_directive(sid)
        out = self._fire({
            "session_id": sid,
            "cwd": str(self.root),
            "hook_event_name": "Stop",
        })
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "hello from evo" in out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_pretooluse_edit_denied_when_subagents_only_for_kimi(self):
        sid = "kimi-test-sid"
        register_session(self.root, sid, "kimi")
        mark_optimize_mode(self.root, sid)
        mark_subagents_only(self.root, sid)
        out = self._fire({
            "session_id": sid,
            "cwd": str(self.root),
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"path": "agent.py"},
        })
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "EVO POLICY" in out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_even_violation_does_not_deny_or_consume_directive_on_kimi(self):
        """The policy-block cadence denies odd violations and lets even ones
        through. On the even pass a Kimi preToolUse must NOT deny the tool the
        cadence intends to allow, and must NOT consume a pending directive on a
        pre-tool event — it waits for the turn-end Stop."""
        from evo.inject import marker
        sid = "kimi-test-sid"
        register_session(self.root, sid, "kimi")
        mark_optimize_mode(self.root, sid)
        mark_subagents_only(self.root, sid)
        self._queue_directive(sid)
        denied = {
            "session_id": sid,
            "cwd": str(self.root),
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"path": "agent.py"},
        }
        # 1st violation (odd): hard deny, directive preserved.
        first = self._fire(denied)
        assert first["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert marker.exists(self.root, sid)
        # 2nd violation (even): tool allowed through, directive still pending.
        second = self._fire(denied)
        assert second == {}, "even violation must not emit a deny envelope"
        assert marker.exists(self.root, sid), "directive consumed on a pre-tool event"


def test_kimi_is_not_env_detectable(monkeypatch):
    """Kimi exports no session env var — it stamps `session_id` onto the hook
    payload instead. Registering a env var here would make `detect_session`
    claim a host it can never actually resolve."""
    for var in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID",
                "HERMES_SESSION_ID", "OPENCODE_SESSION_ID"):
        monkeypatch.delenv(var, raising=False)
    assert detect_session() is None
    assert not any(host == "kimi" for host, _ in HOST_SESSION_ENV_VARS)
