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
