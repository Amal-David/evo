#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


OPENCODE_BUILD_OLD = '''    args.push(options.prompt);
    return commandWithOptionalEnv("opencode", args, opencodeEnv(options.allow));
}
function buildInteractiveOpencode(options) {'''

OPENCODE_BUILD_NEW = '''    const command = commandWithOptionalEnv("opencode", args, opencodeEnv(options.allow));
    if (options.promptFile) {
        return { ...command, stdinFile: options.promptFile };
    }
    args.push(options.prompt);
    return command;
}
function buildInteractiveOpencode(options) {'''

OPENCODE_MODE_OLD = '''    opencode: {
        name: "opencode",
        promptFileMode: "argument",'''

OPENCODE_MODE_NEW = '''    opencode: {
        name: "opencode",
        promptFileMode: "stdin",'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    matches = source.count(old)
    if matches != 1:
        raise ValueError(f"expected one {label} match, found {matches}")
    return source.replace(old, new, 1)


def patch_source(source: str) -> str:
    source = replace_once(
        source,
        OPENCODE_BUILD_OLD,
        OPENCODE_BUILD_NEW,
        "OpenCode command builder",
    )
    return replace_once(
        source,
        OPENCODE_MODE_OLD,
        OPENCODE_MODE_NEW,
        "OpenCode prompt-file mode",
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_headless.py <dist/agents.js>")

    target = Path(sys.argv[1])
    source = target.read_text(encoding="utf-8")
    target.write_text(patch_source(source), encoding="utf-8")


if __name__ == "__main__":
    main()
