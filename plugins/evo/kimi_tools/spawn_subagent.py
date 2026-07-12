#!/usr/bin/env python3
"""Kimi plugin tool: record the mapping between a Kimi Agent and an evo experiment."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from _bootstrap import add_evo_src_to_path

add_evo_src_to_path()

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
        run_dir = workspace_path(root) if root else None

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
