from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "deploy" / "render" / "flock" / "Dockerfile"
RESEARCH = ROOT / "deploy" / "render" / "shinka-flock" / "research.sh"
SANDBOX = ROOT / "deploy" / "render" / "shinka-flock" / "render-bwrap.c"


def test_image_replaces_unavailable_bubblewrap_with_landlock_adapter() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    sandbox = SANDBOX.read_text(encoding="utf-8")

    assert "libseccomp-dev" in dockerfile
    assert "render-bwrap.c -lseccomp -o /usr/bin/bwrap" in dockerfile
    assert "SYS_landlock_restrict_self" in sandbox
    assert '"socket"' in sandbox
    assert '"process_vm_readv"' in sandbox
    assert '"io_uring_setup"' in sandbox


def test_research_fails_closed_until_trusted_baseline_is_correct() -> None:
    research = RESEARCH.read_text(encoding="utf-8")
    preflight = research.index("baseline-preflight")
    correctness_gate = research.index(".correct == true")
    launch = research.index("Launching ShinkaEvolve attempt")

    assert 'echo v2 > "$state_dir/shinka-supervisor-version"' in research
    assert preflight < correctness_gate < launch
    assert "shinka-baseline-ready" in research
    assert "shinka-near-miss-seed-ready" in research
    assert "yukon reset \"$seed_submission\"" in research
    assert "git worktree add --quiet --detach" in research
    assert 'seed_lineage="${seed_submission:0:8}-${recorded_seed_sha:0:12}"' in research
    assert "$target_id/$seed_lineage/landlock-seccomp-v1" in research
