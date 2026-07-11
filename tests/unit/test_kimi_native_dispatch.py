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
