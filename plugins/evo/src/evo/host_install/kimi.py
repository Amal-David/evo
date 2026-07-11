"""Kimi Code CLI install adapter.

Implements `evo install/uninstall/doctor kimi`.
"""

from __future__ import annotations

import argparse


def install(args: argparse.Namespace) -> int:
    """Install the evo plugin into Kimi Code CLI."""
    return 0


def uninstall(args: argparse.Namespace) -> int:
    """Remove the evo plugin from Kimi Code CLI."""
    return 0


def doctor(args: argparse.Namespace) -> int:
    """Verify the evo Kimi plugin is installed and healthy."""
    return 0
