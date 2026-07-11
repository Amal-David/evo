"""Kimi Code CLI host install adapter.

Installs evo as a Kimi plugin by copying the plugin root into Kimi's
managed plugin directory. Also wires hooks via the plugin manifest.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

_RELEASE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([.\-+a-zA-Z0-9]*)$")


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
    # The plugin root is at plugins/evo, one level above the package root.
    here = Path(__file__).resolve().parent.parent.parent.parent  # plugins/evo
    return here


def _github_tarball_url(version: str) -> str:
    ref = f"v{version}" if _RELEASE_VERSION_RE.match(version) else version
    if _RELEASE_VERSION_RE.match(version):
        return f"https://github.com/evo-hq/evo/archive/refs/tags/{ref}.tar.gz"
    return f"https://github.com/evo-hq/evo/archive/refs/heads/{ref}.tar.gz"


def _find_extracted_plugin_root(extracted: Path) -> Path | None:
    """Locate the evo plugin root inside an extracted GitHub archive."""
    direct = extracted / "plugins" / "evo"
    if (direct / ".kimi-plugin" / "plugin.json").exists():
        return direct
    for child in extracted.iterdir():
        if child.is_dir():
            candidate = child / "plugins" / "evo"
            if (candidate / ".kimi-plugin" / "plugin.json").exists():
                return candidate
    return None


def _copy_plugin_root(src: Path, dst: Path) -> None:
    """Copy the plugin root to the Kimi managed plugin directory."""
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


def _install_from_github(version: str) -> int:
    """Download the evo plugin source from GitHub and install it for Kimi."""
    url = _github_tarball_url(version)
    print(f"downloading {url}")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            tarball_bytes = response.read()
    except urllib.error.URLError as exc:
        print(f"ERROR: could not download {url}: {exc}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        tarball_path = Path(tmp) / "evo.tar.gz"
        tarball_path.write_bytes(tarball_bytes)
        extract_dir = Path(tmp) / "extracted"
        extract_dir.mkdir()
        with tarfile.open(tarball_path, "r:gz") as tar:
            # `filter` was added in Python 3.12; keep compatibility with 3.10/3.11.
            extract_kwargs = {"filter": "data"} if sys.version_info >= (3, 12) else {}
            tar.extractall(path=extract_dir, **extract_kwargs)

        src = _find_extracted_plugin_root(extract_dir)
        if src is None:
            print(
                "ERROR: downloaded archive does not contain a valid evo plugin root "
                "(expected .../plugins/evo/.kimi-plugin/plugin.json)",
                file=sys.stderr,
            )
            return 2

        _copy_plugin_root(src, _kimi_plugin_dir())

    print(
        "\n✓ evo installed for kimi.\n"
        "  Start a new Kimi session (or run /reload) to load the plugin."
    )
    return 0


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
        return _install_from_github(version)

    src = _plugin_root(from_path)
    if not src.exists():
        print(f"ERROR: evo plugin source not found at {src}", file=sys.stderr)
        return 2

    _copy_plugin_root(src, _kimi_plugin_dir())

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
