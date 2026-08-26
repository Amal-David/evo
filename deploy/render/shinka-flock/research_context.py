from __future__ import annotations

from pathlib import Path


MAX_RESEARCH_SEED_BYTES = 96 * 1024
REQUIRED_SEED_HEADER = "# Flock x86 research seed for ShinkaEvolve"


def load_research_seed(path: str | Path) -> str:
    seed_path = Path(path)
    payload = seed_path.read_bytes()
    if len(payload) > MAX_RESEARCH_SEED_BYTES:
        raise ValueError(
            f"research seed is {len(payload)} bytes; "
            f"limit is {MAX_RESEARCH_SEED_BYTES}"
        )
    text = payload.decode("utf-8")
    if REQUIRED_SEED_HEADER not in text:
        raise ValueError("research seed is missing its required identity header")
    if "\x00" in text:
        raise ValueError("research seed contains a NUL byte")
    return text.strip()
