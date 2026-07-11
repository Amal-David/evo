"""Kimi Code CLI host install adapter.

Installs evo as a Kimi plugin by copying the plugin root into Kimi's
managed plugin directory. Also wires hooks via the plugin manifest.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _kimi_base() -> Path:
    home_override = os.environ.get("KIMI_CODE_HOME")
    return Path(home_override) if home_override else Path.home() / ".kimi"


def _kimi_plugin_dir() -> Path:
    return _kimi_base() / "plugins" / "managed" / "evo"


def _plugin_root(from_path: str | None = None) -> Path:
    if from_path:
        p = Path(from_path).resolve()
        candidate = p / "plugins" / "evo"
        if candidate.exists():
            return candidate
        if (p / ".kimi-plugin" / "plugin.json").exists() or (p / "kimi.plugin.json").exists():
            return p
        return candidate
    # Running from an installed evo-hq-cli wheel: locate the plugin root
    # relative to this source file (plugins/evo/src/evo/host_install/).
    here = Path(__file__).resolve().parent.parent.parent  # plugins/evo
    return here


def _release_version_re():
    import re
    return re.compile(r"^\d+\.\d+\.\d+([.\-+a-zA-Z0-9]*)$")


def _github_source(version: str) -> str:
    ref = f"v{version}" if _release_version_re().match(version) else version
    return f"https://github.com/evo-hq/evo/tree/{ref}/plugins/evo"


def install(args: argparse.Namespace) -> int:
    if shutil.which("kimi") is None:
        print(
            "ERROR: `kimi` binary not on PATH. Install Kimi Code CLI first:\n"
            "  npm install -g @moonshot-ai/kimi-code-cli",
            file=sys.stderr,
        )
        return 2

    version = getattr(args, "version", None)
    from_path = getattr(args, "from_path", None)

    if version:
        # Let Kimi fetch the plugin from GitHub.
        source = _github_source(version)
        cmd = ["kimi", "plugin", "install", source]
        print(f"$ {' '.join(cmd)}")
        rc = subprocess.call(cmd)
        if rc != 0:
            return rc
        print(
            "\n✓ evo installed for kimi.\n"
            "  Start a new Kimi session (or run /reload) to load the plugin."
        )
        return 0

    src = _plugin_root(from_path)
    if not src.exists():
        print(f"ERROR: evo plugin source not found at {src}", file=sys.stderr)
        return 2

    dst = _kimi_plugin_dir()
    if dst.exists():
        print(f"removing previous install at {dst}")
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"copying {src} -> {dst}")
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "__pycache__", "build", "dist",
            ".pytest_cache", "*.egg-info", "node_modules",
        ),
    )

    print(
        "\n✓ evo installed for kimi.\n"
        "  Start a new Kimi session (or run /reload) to load the plugin."
    )
    return 0


def uninstall(args: argparse.Namespace) -> int:
    dst = _kimi_plugin_dir()
    if dst.exists():
        shutil.rmtree(dst)
        print(f"removed {dst}")
    else:
        print("evo plugin not installed for kimi")
    return 0


def doctor(args: argparse.Namespace) -> int:
    if shutil.which("kimi") is None:
        print("✗ `kimi` binary not on PATH")
        print("  Install: npm install -g @moonshot-ai/kimi-code-cli")
        return 1
    print(f"✓ kimi binary: {shutil.which('kimi')}")

    dst = _kimi_plugin_dir()
    manifest = dst / ".kimi-plugin" / "plugin.json"
    if not manifest.exists():
        manifest = dst / "kimi.plugin.json"
    if not manifest.exists():
        print(f"✗ evo plugin not found at {dst}")
        print("  Run: evo install kimi")
        return 1
    print(f"✓ evo plugin manifest at {manifest}")

    # Basic manifest sanity
    import json
    try:
        data = json.loads(manifest.read_text())
    except json.JSONDecodeError as exc:
        print(f"✗ could not parse manifest: {exc}")
        return 1
    if data.get("name") != "evo":
        print(f"✗ manifest name mismatch: {data.get('name')!r}")
        return 1
    print("✓ manifest name is 'evo'")
    return 0
