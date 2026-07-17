#!/usr/bin/env python3
"""Single-source release-version bumper for the evo plugin.

Updates every file that hardcodes the package version so a release
doesn't leave one of them stale. Locations covered:

  pyproject.toml             project.version
  src/evo/__init__.py        __version__
  .claude-plugin/plugin.json "version"
  .codex-plugin/plugin.json  "version"
  .kimi-plugin/plugin.json   "version"
  npm/package.json           "version"
  skills/*/SKILL.md          evo_version frontmatter
  skills/discover/SKILL.md   step-0 user-facing literals
                             (evo-hq-cli X.Y.Z, install commands)
  CITATION.cff               version + date-released (repo root)

After updating sources, syncs the npm copy of skills (so
npm/skills/*/SKILL.md tracks the source) by running
npm/scripts/sync-from-source.sh.

Usage:
  python plugins/evo/scripts/bump-version.py 0.4.5
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "evo"
SDK_PYTHON_ROOT = REPO_ROOT / "sdk" / "python"
SDK_NODE_ROOT = REPO_ROOT / "sdk" / "node"

# Skills that ship `evo_version` frontmatter. Keep in sync with
# plugins/evo/skills/ subdirs and npm/scripts/sync-from-source.sh.
SKILLS = (
    "discover",
    "optimize",
    "subagent",
    "infra-setup",
    "report",
    "ship",
    "finetuning",
)

# Discover skill's step-0 has user-facing version literals in its body
# (not just frontmatter). Regex-replace the old version anywhere it
# appears in the file — the frontmatter `evo_version` plus the four
# step-0 references all share the same N.M.K shape.
_VERSION_LITERAL_FILES = (
    PLUGIN_ROOT / "skills" / "discover" / "SKILL.md",
)


def _semver_ok(s: str) -> bool:
    return bool(re.fullmatch(r"\d+\.\d+\.\d+(?:[.\-+a-zA-Z0-9]*)", s))


def _read_current_version() -> str:
    text = (PLUGIN_ROOT / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit("could not parse current version from pyproject.toml")
    return m.group(1)


def _bump_pyproject_version(path: Path, new: str) -> None:
    if not path.exists():
        return
    text = path.read_text()
    new_text = re.sub(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{new}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    path.write_text(new_text)


def _bump_init_dunder(path: Path, new: str) -> None:
    if not path.exists():
        return
    text = path.read_text()
    new_text = re.sub(
        r'^__version__\s*=\s*"[^"]+"',
        f'__version__ = "{new}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    path.write_text(new_text)


def _bump_json_version(path: Path, new: str) -> None:
    """Regex-replace the version field, preserving the file's existing
    formatting (json.loads/dumps round-trips collapse single-line arrays
    into multi-line and create spurious diffs)."""
    if not path.exists():
        return
    text = path.read_text()
    pattern = r'("version"\s*:\s*")[^"]+(")'
    new_text, n = re.subn(pattern, rf'\g<1>{new}\g<2>', text, count=1)
    if n == 0:
        raise SystemExit(f"no 'version' field in {path}")
    path.write_text(new_text)
    # Sanity check the file still parses as JSON.
    json.loads(new_text)


def _bump_skill_frontmatter(name: str, new: str) -> None:
    p = PLUGIN_ROOT / "skills" / name / "SKILL.md"
    if not p.exists():
        # Skill listed in SKILLS but not yet on disk — fine, e.g. a new
        # skill in progress on a branch. Caller logs the skip.
        return
    text = p.read_text()
    if re.search(r'^evo_version:\s*', text, re.MULTILINE):
        new_text = re.sub(
            r'^evo_version:\s*\S+',
            f'evo_version: {new}',
            text,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        # Insert before the closing `---` of frontmatter.
        m = re.search(r'^---\n(.*?)\n---\n', text, re.DOTALL | re.MULTILINE)
        if not m:
            raise SystemExit(f"no YAML frontmatter in {p}")
        body = m.group(1)
        new_frontmatter = body + f"\nevo_version: {new}"
        new_text = text[: m.start(1)] + new_frontmatter + text[m.end(1):]
    p.write_text(new_text)


def _bump_body_literals(path: Path, old: str, new: str) -> None:
    """Replace `old` version literals with `new` inside the file body.

    Matches `old` only as a complete version token (not when it's the
    prefix of a longer version). A blind str.replace would re-expand the
    suffix when bumping to a pre-release of the same base — 0.4.4 ->
    0.4.4-alpha.1 would corrupt the frontmatter line this script just
    wrote into 0.4.4-alpha.1-alpha.1."""
    text = path.read_text()
    new_text = re.sub(re.escape(old) + r"(?![\w.+-])", new, text)
    path.write_text(new_text)


def _bump_citation_cff(path: Path, new: str) -> None:
    """Update version + date-released so the citation Zenodo and GitHub
    surface from CITATION.cff always matches the released package."""
    if not path.exists():
        return
    text = path.read_text()
    new_text, n = re.subn(
        r'^version:\s*\S+',
        f'version: {new}',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n == 0:
        raise SystemExit(f"no 'version:' field in {path}")
    today = datetime.date.today().isoformat()
    new_text, n = re.subn(
        r'^date-released:\s*\S+',
        f'date-released: {today}',
        new_text,
        count=1,
        flags=re.MULTILINE,
    )
    if n == 0:
        raise SystemExit(f"no 'date-released:' field in {path}")
    path.write_text(new_text)


def _run_npm_sync() -> None:
    script = PLUGIN_ROOT / "npm" / "scripts" / "sync-from-source.sh"
    subprocess.run(["bash", str(script)], check=True, cwd=REPO_ROOT)


def _verify_no_leftover(old: str, new: str) -> list[Path]:
    """Sanity check — return any plugin file still containing the OLD
    version literal as a standalone version (not as part of a longer
    string like a changelog entry)."""
    leftover: list[Path] = []
    # Match OLD only as a complete token so a pre-release bump of the same
    # base (0.4.4 -> 0.4.4-alpha.1) doesn't flag every file just because
    # NEW contains OLD as a prefix.
    old_token = re.compile(re.escape(old) + r"(?![\w.+-])")
    candidates = [
        PLUGIN_ROOT / "pyproject.toml",
        PLUGIN_ROOT / "src" / "evo" / "__init__.py",
        PLUGIN_ROOT / ".claude-plugin" / "plugin.json",
        PLUGIN_ROOT / ".codex-plugin" / "plugin.json",
        PLUGIN_ROOT / ".kimi-plugin" / "plugin.json",
        PLUGIN_ROOT / "npm" / "package.json",
        SDK_PYTHON_ROOT / "pyproject.toml",
        SDK_PYTHON_ROOT / "src" / "evo_agent" / "__init__.py",
        SDK_NODE_ROOT / "package.json",
        REPO_ROOT / "CITATION.cff",
    ]
    for name in SKILLS:
        candidates.append(PLUGIN_ROOT / "skills" / name / "SKILL.md")
        candidates.append(PLUGIN_ROOT / "npm" / "skills" / name / "SKILL.md")
    for p in candidates:
        if not p.exists():
            continue
        if old_token.search(p.read_text()):
            leftover.append(p)
    return leftover


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("new_version", help="target version, e.g. 0.4.5")
    parser.add_argument(
        "--skip-npm-sync", action="store_true",
        help="don't run npm/scripts/sync-from-source.sh after bumping",
    )
    args = parser.parse_args()

    if not _semver_ok(args.new_version):
        print(f"error: '{args.new_version}' is not a valid version", file=sys.stderr)
        return 2

    old = _read_current_version()
    new = args.new_version
    if old == new:
        print(f"version already {new}; nothing to do")
        return 0
    print(f"bumping {old} → {new}")

    _bump_pyproject_version(PLUGIN_ROOT / "pyproject.toml", new)
    print(f"  ✓ plugins/evo/pyproject.toml (evo-hq-cli)")
    _bump_init_dunder(PLUGIN_ROOT / "src" / "evo" / "__init__.py", new)
    print(f"  ✓ plugins/evo/src/evo/__init__.py (__version__)")
    _bump_json_version(PLUGIN_ROOT / ".claude-plugin" / "plugin.json", new)
    print(f"  ✓ plugins/evo/.claude-plugin/plugin.json")
    _bump_json_version(PLUGIN_ROOT / ".codex-plugin" / "plugin.json", new)
    print(f"  ✓ plugins/evo/.codex-plugin/plugin.json")
    _bump_json_version(PLUGIN_ROOT / ".kimi-plugin" / "plugin.json", new)
    print(f"  ✓ plugins/evo/.kimi-plugin/plugin.json")
    _bump_json_version(PLUGIN_ROOT / "npm" / "package.json", new)
    print(f"  ✓ plugins/evo/npm/package.json (@evo-hq/pi-evo)")

    # SDKs ship in lockstep with the plugin (see check_versions.py and
    # the project_evo_release_checklist memory). A bump that misses any
    # of these makes CI fail.
    _bump_pyproject_version(SDK_PYTHON_ROOT / "pyproject.toml", new)
    print(f"  ✓ sdk/python/pyproject.toml (evo-hq-agent)")
    _bump_init_dunder(
        SDK_PYTHON_ROOT / "src" / "evo_agent" / "__init__.py", new,
    )
    print(f"  ✓ sdk/python/src/evo_agent/__init__.py (__version__)")
    _bump_json_version(SDK_NODE_ROOT / "package.json", new)
    print(f"  ✓ sdk/node/package.json (@evo-hq/evo-agent)")

    _bump_citation_cff(REPO_ROOT / "CITATION.cff", new)
    print(f"  ✓ CITATION.cff (version + date-released)")

    for name in SKILLS:
        skill_path = PLUGIN_ROOT / "skills" / name / "SKILL.md"
        if not skill_path.exists():
            print(f"  · skills/{name}/SKILL.md (skip — not on disk)")
            continue
        _bump_skill_frontmatter(name, new)
        print(f"  ✓ skills/{name}/SKILL.md (evo_version)")

    for path in _VERSION_LITERAL_FILES:
        _bump_body_literals(path, old, new)
        print(f"  ✓ {path.relative_to(REPO_ROOT)} (body literals)")

    if not args.skip_npm_sync:
        print("syncing npm/ from source ...")
        _run_npm_sync()

    leftover = _verify_no_leftover(old, new)
    if leftover:
        print(
            f"\nWARNING: old version '{old}' still appears in:",
            file=sys.stderr,
        )
        for p in leftover:
            print(f"  {p.relative_to(REPO_ROOT)}", file=sys.stderr)
        print(
            "Could be a CHANGELOG/migration entry (fine) or a missed location. Check.",
            file=sys.stderr,
        )

    print(f"\ndone. version is now {new}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
