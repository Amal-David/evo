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
