#!/usr/bin/env python3
"""Kimi plugin tool: poll the evo experiment result for a given Kimi Agent id."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "evo" / "src"))

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
        run_dir = workspace_path(root) if root else None

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
