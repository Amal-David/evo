import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "plugins" / "evo" / ".kimi-plugin" / "plugin.json"
COMMANDS_DIR = REPO_ROOT / "plugins" / "evo" / "commands"
OPTIMIZE_SKILL = REPO_ROOT / "plugins" / "evo" / "skills" / "optimize" / "SKILL.md"

# Capability keys kimi-code reads off a plugin manifest. Anything else is
# either ignored or explicitly rejected — see _UNSUPPORTED_FIELDS.
_SUPPORTED_FIELDS = {
    "name", "version", "description", "keywords", "homepage", "license",
    "author", "skills", "sessionStart", "mcpServers", "hooks", "commands",
    "interface", "skillInstructions",
}

# kimi-code's own UNSUPPORTED_RUNTIME_FIELDS list (verified against 0.26.0).
# A manifest carrying any of these gets a "not supported by Kimi plugins"
# diagnostic and the field is dropped, so declaring one here would ship a
# capability that silently never exists at runtime.
_UNSUPPORTED_FIELDS = {"tools", "apps", "inject", "configFile", "config_file", "bootstrap"}

# Hook events kimi-code accepts (HOOK_EVENT_TYPES). PascalCase, not camelCase.
_HOOK_EVENTS = {
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
    "PermissionResult", "UserPromptSubmit", "Stop", "StopFailure",
    "Interrupt", "SessionStart", "SubagentStop",
}


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def test_manifest_exists_and_is_valid_json():
    assert MANIFEST.exists(), f"manifest not found at {MANIFEST}"
    data = _manifest()
    assert data["name"] == "evo"
    assert "version" in data
    assert "skills" in data
    assert "commands" in data
    assert "hooks" in data


def test_manifest_declares_no_unsupported_fields():
    """Kimi drops these with a diagnostic rather than honoring them."""
    present = _UNSUPPORTED_FIELDS & set(_manifest())
    assert not present, (
        f"manifest declares {sorted(present)}, which kimi-code lists in "
        "UNSUPPORTED_RUNTIME_FIELDS and will never load"
    )


def test_manifest_fields_are_all_readable_by_kimi():
    unknown = set(_manifest()) - _SUPPORTED_FIELDS
    assert not unknown, f"manifest declares keys kimi never reads: {sorted(unknown)}"


def test_skills_and_commands_are_relative_paths():
    """Kimi requires plugin path fields to start with './'."""
    data = _manifest()
    for field in ("skills", "commands"):
        value = data[field]
        assert isinstance(value, str), f"{field} must be a string or string[]"
        assert value.startswith("./"), f"{field} must be plugin-root-relative, got {value!r}"


def test_hooks_use_supported_events_and_shape():
    for hook in _manifest()["hooks"]:
        assert set(hook) <= {"event", "matcher", "command", "timeout"}, (
            f"hook has keys outside kimi's HookDefSchema: {sorted(hook)}"
        )
        assert hook["event"] in _HOOK_EVENTS, f"unknown hook event {hook['event']!r}"
        assert hook["command"], "hook command must be non-empty"


def test_hooks_route_drain_through_the_kimi_host():
    commands = {hook["command"] for hook in _manifest()["hooks"]}
    assert commands == {"evo-drain --host kimi"}


def test_discover_command_file_exists():
    assert (COMMANDS_DIR / "discover.md").exists()


def test_optimize_command_file_exists():
    assert (COMMANDS_DIR / "optimize.md").exists()


def test_optimize_skill_documents_kimi_spawn_shape():
    text = OPTIMIZE_SKILL.read_text()
    assert "**kimi**" in text
    assert "Agent(run_in_background=true)" in text


def test_optimize_skill_does_not_reference_plugin_tools():
    """The tools these named were never loadable; the skill must not tell the
    model to call them."""
    text = OPTIMIZE_SKILL.read_text()
    for name in ("evo_spawn_subagent", "evo_wait_subagent"):
        assert name not in text, f"skill still instructs the model to call {name}"
