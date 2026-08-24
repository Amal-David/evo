"""Tests for the fail-closed headless OpenCode launcher."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "evo" / "src"))

from evo.cli import build_parser, cmd_opencode_run


class TestOpencodeRun(unittest.TestCase):
    def _args(self, **overrides) -> argparse.Namespace:
        values = {
            "phase": "discover",
            "goal": "maximize the proved bound",
            "model": "opencode/x-preview-f-free",
            "variant": None,
            "no_auto": False,
            "subagents": None,
            "budget": None,
            "stall": None,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_parser_requires_an_explicit_phase(self):
        args = build_parser().parse_args([
            "opencode-run", "discover", "--goal", "maximize the proved bound",
            "--model", "opencode/x-preview-f-free",
        ])
        self.assertEqual(args.phase, "discover")
        self.assertEqual(args.func, cmd_opencode_run)

    def test_discover_execs_exact_skill_invocation(self):
        with patch("evo.cli.shutil.which", return_value="/bin/opencode"), \
             patch("evo.cli.os.execvpe") as execvpe:
            rc = cmd_opencode_run(self._args())

        self.assertEqual(rc, 127)
        command = execvpe.call_args.args[1]
        self.assertEqual(command[:5], [
            "/bin/opencode", "run", "--auto", "--model",
            "opencode/x-preview-f-free",
        ])
        self.assertEqual(command[-1], "/discover Goal: maximize the proved bound")

    def test_reasoning_variant_is_forwarded(self):
        with patch("evo.cli.shutil.which", return_value="/bin/opencode"), \
             patch("evo.cli.os.execvpe") as execvpe:
            rc = cmd_opencode_run(self._args(variant="max"))

        self.assertEqual(rc, 127)
        command = execvpe.call_args.args[1]
        self.assertEqual(command[-3:], [
            "--variant", "max", "/discover Goal: maximize the proved bound",
        ])

    def test_optimize_shape_is_forwarded_to_native_evo_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".evo").mkdir()
            (root / ".evo" / "project.md").write_text("# Project\n")
            previous = Path.cwd()
            os.chdir(root)
            try:
                with patch("evo.cli.shutil.which", return_value="/bin/opencode"), \
                     patch("evo.cli.os.execvpe") as execvpe:
                    rc = cmd_opencode_run(self._args(
                        phase="optimize", subagents=2, budget=8, stall=20,
                    ))
            finally:
                os.chdir(previous)

        self.assertEqual(rc, 127)
        self.assertEqual(
            execvpe.call_args.args[1][-1],
            "/optimize subagents=2 budget=8 stall=20 Goal: maximize the proved bound",
        )

    def test_discover_rejects_optimize_shape(self):
        with patch("evo.cli.shutil.which", return_value="/bin/opencode"), \
             patch("evo.cli.os.execvpe") as execvpe:
            rc = cmd_opencode_run(self._args(subagents=2))

        self.assertEqual(rc, 2)
        execvpe.assert_not_called()

    def test_optimize_shape_requires_positive_integers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".evo").mkdir()
            (root / ".evo" / "project.md").write_text("# Project\n")
            previous = Path.cwd()
            os.chdir(root)
            try:
                with patch("evo.cli.shutil.which", return_value="/bin/opencode"), \
                     patch("evo.cli.os.execvpe") as execvpe:
                    rc = cmd_opencode_run(self._args(phase="optimize", budget=0))
            finally:
                os.chdir(previous)

        self.assertEqual(rc, 2)
        execvpe.assert_not_called()

    def test_empty_goal_fails_before_launch(self):
        with patch("evo.cli.shutil.which", return_value="/bin/opencode"), \
             patch("evo.cli.os.execvpe") as execvpe:
            rc = cmd_opencode_run(self._args(goal="  "))

        self.assertEqual(rc, 2)
        execvpe.assert_not_called()

    def test_optimize_refuses_an_uninitialized_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                with patch("evo.cli.shutil.which", return_value="/bin/opencode"), \
                     patch("evo.cli.os.execvpe") as execvpe:
                    rc = cmd_opencode_run(self._args(phase="optimize"))
            finally:
                os.chdir(previous)

        self.assertEqual(rc, 2)
        execvpe.assert_not_called()

    def test_missing_opencode_fails_before_launch(self):
        with patch("evo.cli.shutil.which", return_value=None), \
             patch("evo.cli.os.execvpe") as execvpe:
            rc = cmd_opencode_run(self._args())

        self.assertEqual(rc, 2)
        execvpe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
