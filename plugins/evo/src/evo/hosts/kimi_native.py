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
