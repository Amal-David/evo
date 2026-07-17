"""Guards that every host plugin manifest is wired into the release tooling.

Each host ships its own `.<host>-plugin/plugin.json` carrying a hardcoded
version, and hosts key off that version to decide whether to refetch the
plugin. A manifest the bumper doesn't know about silently keeps its old
version through a release, so the host never refetches and stays pinned to
the previous CLI. Adding a manifest without registering it here is the whole
failure mode these tests exist to catch.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "evo"
BUMP_SCRIPT = PLUGIN_ROOT / "scripts" / "bump-version.py"
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_versions.py"


def _host_manifests() -> list[Path]:
    """Every host plugin manifest actually on disk."""
    return sorted(PLUGIN_ROOT.glob(".*-plugin/plugin.json"))


def _check_versions_sources() -> set[str]:
    spec = importlib.util.spec_from_file_location("check_versions", CHECK_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {path for path, _label in module.SOURCES}


def test_host_manifests_are_discovered():
    """Sanity: the glob finds real manifests, so the guards below can't pass
    vacuously."""
    found = {p.parent.name for p in _host_manifests()}
    assert {".claude-plugin", ".codex-plugin", ".kimi-plugin"} <= found


def test_every_host_manifest_is_version_checked():
    # SOURCES holds forward-slash repo-relative literals; normalize the
    # manifest paths the same way so the comparison holds on Windows, where
    # str(Path) uses backslashes.
    sources = _check_versions_sources()
    missing = [
        rel for rel in (m.relative_to(REPO_ROOT).as_posix() for m in _host_manifests())
        if rel not in sources
    ]
    assert not missing, (
        f"{missing} not listed in scripts/check_versions.py SOURCES — a release "
        "would not notice these going stale"
    )


def test_every_host_manifest_is_bumped():
    text = BUMP_SCRIPT.read_text()
    missing = [m.parent.name for m in _host_manifests() if m.parent.name not in text]
    assert not missing, (
        f"{missing} not handled by bump-version.py — the manifest would keep its "
        "old version through a release and the host would never refetch"
    )


def test_all_host_manifests_report_the_same_version():
    versions = {
        m.parent.name: json.loads(m.read_text())["version"] for m in _host_manifests()
    }
    assert len(set(versions.values())) == 1, f"host manifests disagree: {versions}"
