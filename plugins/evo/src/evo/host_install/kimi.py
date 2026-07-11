"""Placeholder Kimi host install adapter.

This module is a temporary stub for `evo install/uninstall/doctor kimi`.
The real implementation will be added in Task 2.
"""

from __future__ import annotations

import argparse
import sys


def install(args: argparse.Namespace) -> int:
    """Install the evo plugin into Kimi Code CLI."""
    print(
        "ERROR: Kimi host adapter not yet implemented (Task 2).",
        file=sys.stderr,
    )
    return 1


def uninstall(args: argparse.Namespace) -> int:
    """Remove the evo plugin from Kimi Code CLI."""
    print(
        "ERROR: Kimi host adapter not yet implemented (Task 2).",
        file=sys.stderr,
    )
    return 1


def doctor(args: argparse.Namespace) -> int:
    """Verify the evo Kimi plugin is installed and healthy."""
    print(
        "ERROR: Kimi host adapter not yet implemented (Task 2).",
        file=sys.stderr,
    )
    return 1
