"""Session registry — opt-in via auto-register on first `evo X` call.

A session that never invokes any evo command never appears in the
registry. `evo direct` enumerates registered sessions to fan out
markers; unregistered sessions are invisible.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Iterable

from evo.core import atomic_write_json

from .paths import (
    ensure_dirs,
    inject_root,
    offset_file,
    optimize_mode_dir,
    optimize_mode_flag_file,
    session_file,
    sessions_dir,
)

REGISTRY_SCHEMA_VERSION = 1
# 30 days. The freshness signal is no longer used as an engagement
# heuristic — `has_evo_engaged` is. This just prevents on-disk leakage
# of records for sessions that genuinely died.
STALE_AFTER_SECONDS = 30 * 24 * 60 * 60

# Order matters: first hit wins. Each entry is (host, env_var_name).
# Codex exposes the session as CODEX_THREAD_ID (verified empirically on
# codex-cli 0.130 — it shows "session id: <uuid>" at startup and exports
# the same uuid via CODEX_THREAD_ID, not CODEX_SESSION_ID).
# Cursor and Kimi are absent by design: neither exports a session env var,
# so both resolve the session from the hook stdin payload instead (Kimi
# sends `session_id` on every event; see drain's self-contained path).
HOST_SESSION_ENV_VARS = (
    ("codex", "CODEX_THREAD_ID"),
    ("claude-code", "CLAUDE_CODE_SESSION_ID"),
    ("hermes", "HERMES_SESSION_ID"),
    ("opencode", "OPENCODE_SESSION_ID"),
)


def detect_session() -> tuple[str, str] | None:
    """Detect host + session_id from environment. Returns None if no
    host's session env var is set — meaning we're not running inside
    an evo-aware agent session."""
    for host, env_var in HOST_SESSION_ENV_VARS:
        sid = os.environ.get(env_var)
        if sid:
            return host, sid
    return None


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def register_session(
    root: Path,
    session_id: str,
    host: str,
    *,
    exp_id: str | None = None,
    parent_session_id: str | None = None,
    engage: bool = False,
) -> None:
    """Idempotent: write `<inject>/sessions/<sid>.json` if absent;
    update `last_seen_at` if present.

    Merges non-null `parent_session_id` into an existing record when
    that field is currently empty.

    `exp_id` merge is restricted: a non-null `exp_id` is only merged
    onto a record that is NOT an engaged orchestrator. claude-code and
    codex inherit the parent's CLAUDE_CODE_SESSION_ID / CODEX_THREAD_ID
    when spawning subagents, so a subagent's `auto_register_from_env`
    resolves to the orchestrator's sid and would otherwise stamp
    `EVO_EXP_ID` onto the orchestrator record — re-classifying it as a
    subagent and making `evo direct` skip it (cli.py skipped_subagent).
    Only stamp `exp_id` when the existing record never engaged (so it's
    a genuine subagent-first registration), never onto an engaged
    orchestrator.

    `engage=True` marks the session as evo-engaged at registration — used
    by the SessionStart / orchestrator-process registration paths (Rust
    binary, hermes plugin) where the registering process IS the
    orchestrator. Engagement is refused for subagent registrations
    (non-null `exp_id`): a subagent must never engage the loop on its own.

    Never clobbers a non-null existing value.

    Caller is responsible for only calling this when there's an active
    workspace.
    """
    ensure_dirs(root)
    path = session_file(root, session_id)
    now = _now_iso()
    is_subagent = exp_id is not None
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = None
        if data is not None:
            data["last_seen_at"] = now
            # Ensure engagement + optimize_mode fields exist on records
            # written by older code paths (e.g. the Rust binary's v1
            # schema without these fields). Do this BEFORE the exp_id
            # merge so the engaged-orchestrator guard below sees the
            # real value.
            data.setdefault("has_evo_engaged", False)
            data.setdefault("engaged_at", None)
            data.setdefault("optimize_mode", False)
            data.setdefault("optimize_mode_at", None)
            data.setdefault("autonomous", False)
            data.setdefault("autonomous_at", None)
            data.setdefault("subagents_only", False)
            data.setdefault("subagents_only_at", None)
            # Merge-only: fill in fields that are currently null.
            # exp_id is special: never stamp a subagent's exp_id onto an
            # already-engaged orchestrator record (the inherited-session-id
            # case). That would mis-classify the orchestrator as a
            # subagent and make `evo direct` skip it.
            if (
                exp_id is not None
                and not data.get("exp_id")
                and not data.get("has_evo_engaged")
            ):
                data["exp_id"] = exp_id
            if parent_session_id is not None and not data.get("parent_session_id"):
                data["parent_session_id"] = parent_session_id
            # Orchestrator engagement on a re-registration (e.g. a resumed
            # chat whose SessionStart re-fires). Only engage genuine
            # orchestrators — never a record carrying an exp_id, and never
            # the incoming subagent registration.
            transitioned = False
            if (
                engage
                and not is_subagent
                and not data.get("exp_id")
                and not data.get("has_evo_engaged")
            ):
                data["has_evo_engaged"] = True
                data["engaged_at"] = now
                transitioned = True
            atomic_write_json(path, data)
            if transitioned:
                from .queue import init_offset_to_latest
                init_offset_to_latest(root, session_id)
            return
    engaged = bool(engage and not is_subagent)
    data = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "session_id": session_id,
        "host": host,
        "pid": os.getpid(),
        "registered_at": now,
        "last_seen_at": now,
        "exp_id": exp_id,
        "parent_session_id": parent_session_id,
        "has_evo_engaged": engaged,
        "engaged_at": now if engaged else None,
        # v0.4.5+: optimize_mode tags a session as the orchestrator
        # currently driving /evo:optimize. Set automatically when the
        # user invokes /optimize (UserPromptSubmit pattern-match in
        # drain.py). Drives the policy nudge.
        "optimize_mode": False,
        "optimize_mode_at": None,
        # v0.4.5+: autonomous gates the stop-hook continuation (the
        # always-fire stop nudge). Opt-in only — set when the orchestrator
        # runs `evo autonomous on` (driven by the `autonomous` /optimize
        # param). Default off: a plain /optimize stops naturally at a turn
        # boundary instead of being force-continued until kill.
        "autonomous": False,
        "autonomous_at": None,
        # v0.4.5+: subagents_only gates the policy deny (orchestrator can't
        # edit files / run experiments by hand). Opt-in — set when the
        # orchestrator runs `evo subagents-only on` (driven by the
        # `subagents-only` /optimize param). Default off: a plain /optimize
        # ALLOWS the orchestrator to edit directly; arm this to enforce the
        # delegate-to-subagents discipline.
        "subagents_only": False,
        "subagents_only_at": None,
    }
    atomic_write_json(path, data)
    # Seed the workspace offset to the current queue tail so this session
    # only sees events queued AFTER it registered. Without this, the
    # SessionStart-unconditional-drain in the Rust binary would backfill
    # every pre-existing event in workspace.jsonl, bypassing the
    # engagement filter.
    from .queue import init_offset_to_latest
    init_offset_to_latest(root, session_id)


def claim_current_session_exp_id(root: Path, exp_id: str) -> bool:
    """Stamp the current host session as owning `exp_id` after it allocated
    that experiment with `evo new`.

    Subagents usually do not know their experiment id until `evo new` returns,
    so `auto_register_from_env()` cannot rely solely on `EVO_EXP_ID`. This is a
    narrow post-allocation path: only sessions that have not already engaged as
    an orchestrator may claim an experiment.
    """
    detected = detect_session()
    if not detected:
        return False
    _host, sid = detected
    path = session_file(root, sid)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if data.get("exp_id"):
        return data.get("exp_id") == exp_id
    if data.get("has_evo_engaged") or data.get("optimize_mode") or data.get("subagents_only"):
        return False
    data["exp_id"] = exp_id
    data["exp_id_claimed_at"] = _now_iso()
    data["has_evo_engaged"] = False
    data["engaged_at"] = None
    data["autonomous"] = False
    data["autonomous_at"] = None
    try:
        atomic_write_json(path, data)
    except OSError:
        return False
    return True


def _write_optimize_mode_flag(root: Path, session_id: str) -> None:
    """Drop the empty `inject/optimize_mode/<sid>.flag` side-channel file.
    The Rust hook checks this via stat() to decide whether to hand off
    on tool/stop events without reading the session JSON. Best-effort:
    a missing flag self-heals on the next mark_optimize_mode call or
    via the drain's consistency check."""
    try:
        optimize_mode_dir(root).mkdir(parents=True, exist_ok=True)
        optimize_mode_flag_file(root, session_id).touch(exist_ok=True)
    except OSError:
        pass  # never block on cache-write failures


def _clear_optimize_mode_flag(root: Path, session_id: str) -> None:
    try:
        optimize_mode_flag_file(root, session_id).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def mark_optimize_mode(root: Path, session_id: str) -> bool:
    """Flip `optimize_mode` true on the session record if currently false.

    Refuses to flag a subagent session (one with exp_id set) — subagents
    are never the optimize orchestrator. Returns True on the false→true
    transition, False on no-op (already true, missing record, or
    subagent). Caller should treat True as a signal to (optionally)
    side-effect, e.g. write to telemetry.

    Side-effect on transition: drops `inject/optimize_mode/<sid>.flag`
    as a fast-path side channel for the Rust hook.
    """
    path = session_file(root, session_id)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if data.get("exp_id"):
        return False  # subagent — never tag as orchestrator
    if data.get("optimize_mode"):
        # Self-heal: if the JSON says optimize_mode=true but the flag
        # file is missing (e.g. someone manually cleaned `inject/`),
        # re-create it. Cheap — the touch is idempotent.
        _write_optimize_mode_flag(root, session_id)
        return False
    data["optimize_mode"] = True
    data["optimize_mode_at"] = _now_iso()
    # Fail-open on disk-full / perms: this fires from the hot prompt
    # path. Crashing here would halt the agent. Better to leave
    # optimize_mode unset and let the user re-arm than to block the
    # hook entirely.
    try:
        atomic_write_json(path, data)
    except OSError:
        return False
    _write_optimize_mode_flag(root, session_id)
    return True


def unmark_optimize_mode(root: Path, session_id: str) -> bool:
    """Flip `optimize_mode` false on the session record if currently true.

    Used by the `evo exit-optimize-mode` CLI command. Returns True on
    the true→false transition, False on no-op (already false, missing
    record). Also removes the `inject/optimize_mode/<sid>.flag` side
    channel.
    """
    path = session_file(root, session_id)
    if not path.exists():
        # Still try to clear the flag in case the JSON was already removed
        # but the flag leaked. Cheap.
        _clear_optimize_mode_flag(root, session_id)
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        _clear_optimize_mode_flag(root, session_id)
        return False
    if not data.get("optimize_mode"):
        _clear_optimize_mode_flag(root, session_id)
        return False
    data["optimize_mode"] = False
    data["optimize_mode_at"] = None
    try:
        atomic_write_json(path, data)
    except OSError:
        # Even if the JSON write fails, clear the flag — that's the
        # signal Rust reads. User invoked `evo exit-optimize-mode`
        # explicitly; honor that intent.
        _clear_optimize_mode_flag(root, session_id)
        return False
    _clear_optimize_mode_flag(root, session_id)
    return True


def mark_autonomous(root: Path, session_id: str) -> bool:
    """Flip `autonomous` true on the session record if currently false.

    Autonomous gates the always-fire stop nudge (the loop that
    force-continues the orchestrator at every turn boundary). Opt-in: the
    orchestrator runs `evo autonomous on` when /optimize is invoked with
    the `autonomous` param. No Rust-side flag file is needed — the Rust
    binary already hands off on Stop whenever optimize_mode is set, and
    the Python drain (`_maybe_stop_nudge_text`) reads this field to decide
    whether to actually nudge.

    Refuses to flag a subagent session (one with exp_id set) — subagents
    are never the orchestrator. Returns True on the false→true transition,
    False on no-op (already true, missing record, or subagent). Fail-open
    on disk errors (never crash the agent).
    """
    path = session_file(root, session_id)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if data.get("exp_id"):
        return False  # subagent — never the orchestrator
    if data.get("autonomous"):
        return False
    data["autonomous"] = True
    data["autonomous_at"] = _now_iso()
    try:
        atomic_write_json(path, data)
    except OSError:
        return False
    return True


def unmark_autonomous(root: Path, session_id: str) -> bool:
    """Flip `autonomous` false on the session record if currently true.

    Used by `evo autonomous off` and by `evo exit-optimize-mode` (which
    clears both optimize_mode and autonomous). Returns True on the
    true→false transition, False on no-op.
    """
    path = session_file(root, session_id)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not data.get("autonomous"):
        return False
    data["autonomous"] = False
    data["autonomous_at"] = None
    try:
        atomic_write_json(path, data)
    except OSError:
        return False
    return True


def mark_subagents_only(root: Path, session_id: str) -> bool:
    """Flip `subagents_only` true — enforce the policy deny so the
    orchestrator can't edit files / run experiments by hand (only subagents
    do). Opt-in: set when the orchestrator runs `evo subagents-only on`.
    Refuses subagents (exp_id). Returns True on the false→true transition."""
    path = session_file(root, session_id)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if data.get("exp_id"):
        return False  # subagent — not the orchestrator
    if data.get("subagents_only"):
        return False
    data["subagents_only"] = True
    data["subagents_only_at"] = _now_iso()
    try:
        atomic_write_json(path, data)
    except OSError:
        return False
    return True


def unmark_subagents_only(root: Path, session_id: str) -> bool:
    """Flip `subagents_only` false — allow the orchestrator to edit again.
    Used by `evo subagents-only off` and `evo exit-optimize-mode`."""
    path = session_file(root, session_id)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not data.get("subagents_only"):
        return False
    data["subagents_only"] = False
    data["subagents_only_at"] = None
    try:
        atomic_write_json(path, data)
    except OSError:
        return False
    return True


def mark_engaged(root: Path, session_id: str) -> bool:
    """Flip `has_evo_engaged` true on the session record if currently
    false. Returns True if a transition happened (caller should seed
    the workspace offset to the queue tail to prevent backfill of
    directives queued before engagement). Idempotent — returns False
    on subsequent calls.

    No-op if the session isn't registered.
    """
    path = session_file(root, session_id)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if data.get("exp_id"):
        return False  # subagent — never engage the loop on its own
    if data.get("has_evo_engaged"):
        return False
    data["has_evo_engaged"] = True
    data["engaged_at"] = _now_iso()
    atomic_write_json(path, data)
    return True


def list_active_sessions(root: Path) -> list[dict]:
    """Return all registered (non-stale) session records. Side effect:
    GC's stale entries (and matching offset files)."""
    ensure_dirs(root)
    out: list[dict] = []
    cutoff = time.time() - STALE_AFTER_SECONDS
    for entry in sessions_dir(root).iterdir():
        if not entry.name.endswith(".json"):
            continue
        try:
            data = json.loads(entry.read_text())
        except (OSError, ValueError):
            continue
        last_seen = data.get("last_seen_at")
        try:
            if last_seen:
                # Python 3.10's `fromisoformat` doesn't accept the `Z`
                # suffix that some writers (older Rust binary builds)
                # emit. Translate it to the equivalent `+00:00` for
                # parseability. Python's own writer uses `+00:00` so
                # this is a no-op for Python-written records.
                normalized = last_seen[:-1] + "+00:00" if last_seen.endswith("Z") else last_seen
                ts = dt.datetime.fromisoformat(normalized).timestamp()
            else:
                ts = 0
        except (ValueError, TypeError):
            ts = 0
        if ts < cutoff:
            # Stale — GC the entry and its matching offset file.
            try:
                entry.unlink()
            except FileNotFoundError:
                pass
            sid = data.get("session_id") or entry.stem
            try:
                offset_file(root, sid).unlink()
            except FileNotFoundError:
                pass
            continue
        out.append(data)
    return out


def get_session(root: Path, session_id: str) -> dict | None:
    """Return the registry record for a session, or None if not registered."""
    path = session_file(root, session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def is_registered(root: Path, session_id: str) -> bool:
    return session_file(root, session_id).exists()


def auto_register_from_env(root: Path) -> None:
    """Best-effort: if a host session env var is set, register this
    session AND mark it as evo-engaged. Called from evo CLI's main()
    on every command — running any `evo` subcommand is the engagement
    signal.

    The engagement transition (false → true) seeds the workspace
    offset to the current tail so directives queued before the
    session engaged don't replay on this session. This is the
    "never reach sessions that never engaged" guarantee — once a
    session does engage, only post-engagement directives can deliver.

    No-op if no host env var is set, or if root isn't a workspace.
    """
    if not inject_root(root).parent.exists():
        # No active run dir — not a workspace; nothing to register against.
        return
    detected = detect_session()
    if not detected:
        return
    host, sid = detected
    # If running as a subagent, EVO_EXP_ID is set by the dispatch parent.
    exp_id = os.environ.get("EVO_EXP_ID")
    register_session(root, sid, host, exp_id=exp_id)
    # Local import to avoid a circular module dependency
    # (queue imports atomic_write_json from evo.core; registry doesn't
    # need queue at module load time).
    from .queue import init_offset_to_latest
    transitioned = mark_engaged(root, sid)
    if transitioned:
        init_offset_to_latest(root, sid)
