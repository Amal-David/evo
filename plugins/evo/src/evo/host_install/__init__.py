"""Host plugin install adapters — `evo install <host>` dispatches here.

Each host module exposes:
    install(args) -> int       # 0 success
    uninstall(args) -> int
    doctor(args) -> int        # verify install: paths, configs, basic load

Hosts that have native marketplaces (Claude Code, Codex, OpenClaw) point
the user at the marketplace command. Hosts where evo's setup needs
multiple steps (Hermes, Opencode) implement the steps here.

After every install/update, this module also keeps the global
`evo-hq-cli` (the CLI binary on PATH) in lockstep with the host
plugin's version. The CLI and the host's skills/hooks share a wire
format — schema fields like `optimize_mode`, the policy banner shape,
the hook event names — so drift breaks the loop silently. The
`discover` skill's step-0 (`evo --version` must match the literal in
its body) catches any residual drift, but auto-sync prevents the drift
from appearing in the first place.

See notes/cross-host-inject-design.md.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import claude_code, claude_science, codex, cursor, hermes, kimi, opencode, openclaw, pi

ADAPTERS = {
    "claude-code": claude_code,
    "claude-science": claude_science,
    "codex": codex,
    "cursor": cursor,
    "hermes": hermes,
    "kimi": kimi,
    "opencode": opencode,
    "openclaw": openclaw,
    "pi": pi,
}

# Single source of truth for host names. CLI argparse choices and
# anything else that enumerates supported hosts should read this.
SUPPORTED_HOSTS = sorted(ADAPTERS)


def get(host: str):
    if host not in ADAPTERS:
        valid = ", ".join(SUPPORTED_HOSTS)
        raise ValueError(f"unknown host {host!r} — try one of: {valid}")
    return ADAPTERS[host]


# Module-level guard: `evo update` (bare) refreshes the CLI once at the
# top, then iterates over every healthy host and calls our `update`
# wrapper for each — which would trigger another CLI sync per host
# without this guard. Reset between processes (fresh `evo` invocations
# always start with sync allowed).
_cli_synced_this_run = False


def _mark_cli_synced() -> None:
    global _cli_synced_this_run
    _cli_synced_this_run = True


def install(host: str, args) -> int:
    """Run the host's install + sync the global CLI to match, then run
    the host's doctor. A non-zero doctor result is returned as the
    install's result: an install that doctor can't verify is not a
    success the user should have to discover at hook-fire time.
    """
    rc = get(host).install(args)
    if rc == 0:
        _sync_cli_to_plugin_version(args)
        rc = _verify_install(host)
    return rc


def update(host: str, args) -> int:
    """Run `update(args)` if the adapter defines it, otherwise fall back
    to `install(args)`. Most file-copy hosts (codex/openclaw/opencode)
    treat install as idempotent and update-equivalent — they wipe the
    cache and copy fresh on every install. Claude Code is the exception:
    `claude plugin update` is a distinct subcommand from install.

    After the host update completes, syncs the global CLI to match the
    host plugin's version (skipped for editable installs — see
    `_sync_cli_to_plugin_version`).
    """
    module = get(host)
    fn = getattr(module, "update", None)
    if fn is None:
        fn = module.install
    rc = fn(args)
    if rc == 0:
        _sync_cli_to_plugin_version(args)
        rc = _verify_install(host)
    return rc


def _verify_install(host: str) -> int:
    """Run the host's doctor after a successful install/update so a
    broken result is visible immediately instead of at hook-fire time.
    """
    import argparse
    print(f"\n=== verifying: evo doctor {host} ===")
    return get(host).doctor(argparse.Namespace())


def _is_editable_evo_install() -> bool:
    """Return True if `evo-hq-cli` is currently installed in editable
    mode (uv tool install --editable, pip install -e, or similar).

    Detection: the imported `evo` module's source file lives outside
    any `site-packages` directory — pointing at a working-tree clone
    instead. That's the signature of an editable install, regardless
    of how it was set up.

    Auto-sync skips editable installs because forcing a PyPI reinstall
    would clobber the user's dev workflow (their .pth file pointing
    at the working tree would be wiped).
    """
    try:
        import evo
        evo_file = Path(evo.__file__).resolve()
        return "site-packages" not in evo_file.parts
    except Exception:
        return False


def _sync_cli_to_plugin_version(args) -> int:
    """After a host install/update, ensure the CLI on PATH is the same
    version as the plugin we just installed.

    Decision tree:
      1. Already synced this process → no-op (bare `evo update`
         iterates many hosts; only sync once).
      2. Editable install detected → skip silently, print a hint about
         `--from-path` if the user passed one (their working tree IS
         the source of truth, so the CLI is already in sync).
      3. `--from-path` given but CLI is not editable → can't safely
         sync (would need to install editable from the same path).
         Warn and let the user decide.
      4. `--version X` given → `uv tool install --force evo-hq-cli==X`
      5. Default → `uv tool install --force evo-hq-cli` (PyPI latest)
    """
    global _cli_synced_this_run
    if _cli_synced_this_run:
        return 0

    from_path = getattr(args, "from_path", None)
    version = getattr(args, "version", None)

    if _is_editable_evo_install():
        if from_path:
            print(
                "(CLI is editable — `--from-path` already in sync via the "
                "working tree. Skipping CLI auto-sync.)"
            )
        # When --from-path is NOT set but install is editable, the user
        # is in a dev workflow that they've set up explicitly. Trust
        # them and stay silent.
        _mark_cli_synced()
        return 0

    if from_path:
        # Non-editable CLI with --from-path: the host plugin is now
        # bleeding-edge from a local checkout, but the CLI is whatever
        # uv-tool installed. They could diverge. Suggest the fix but
        # don't auto-do it — installing editable from a path the user
        # might not have intended could be surprising.
        repo_root = Path(from_path).resolve()
        print(
            f"\nNOTE: host plugin installed from {repo_root}, but the CLI "
            "is not editable. To keep them in sync:\n"
            f"  uv tool install --force --editable {repo_root}/plugins/evo\n"
            "Or run `evo update` (no host arg) later to refresh the CLI "
            "from PyPI."
        )
        _mark_cli_synced()
        return 0

    target = "evo-hq-cli"
    if version:
        # Determine if the version is a PyPI-shape release tag. Branch
        # names / SHAs don't exist on PyPI; we can't pin to them.
        if claude_code._looks_like_pypi_release(version):
            target = f"evo-hq-cli=={version}"
        else:
            print(
                f"(skipping CLI auto-sync: --version {version!r} is not a "
                "PyPI release shape — uv tool install only knows about "
                "published versions. CLI stays at current install.)"
            )
            _mark_cli_synced()
            return 0

    cmd = ["uv", "tool", "install", "--force", target]
    print(f"=== Syncing CLI: {' '.join(cmd)} ===")
    rc = subprocess.call(cmd)
    if rc == 0:
        _mark_cli_synced()
    if rc != 0:
        print(
            f"WARNING: CLI auto-sync failed (`uv tool install --force "
            f"{target}` exited {rc}). The host plugin is up to date but "
            "the CLI on PATH may now disagree with it. To recover:\n"
            f"  uv tool install --force {target}  # (manually)\n"
            "or:\n"
            "  pipx install --force evo-hq-cli\n"
            "The discover skill's step-0 version check will surface the "
            "drift on the next /discover invocation so the agent can flag it.",
            file=sys.stderr,
        )
    return rc
