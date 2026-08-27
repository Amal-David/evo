from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "deploy" / "render" / "flock" / "Dockerfile"
RESEARCH = ROOT / "deploy" / "render" / "shinka-flock" / "research.sh"
RUN_EVO = ROOT / "deploy" / "render" / "shinka-flock" / "run_evo.py"
SUBMIT_PROBE = ROOT / "deploy" / "render" / "shinka-flock" / "submit-probe.sh"
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
    assert 'grep -Fq "$seed_source_commit" "$seed_stage/reset.log"' in research
    assert "git worktree add --quiet --detach" in research
    assert 'seed_lineage="${seed_submission:0:8}-${recorded_seed_sha:0:12}"' in research
    assert "$target_id/$seed_lineage/landlock-seccomp-v1" in research


def test_research_reads_the_installed_skill_and_recovers_blocked_candidates() -> None:
    research = RESEARCH.read_text(encoding="utf-8")
    run_evo = RUN_EVO.read_text(encoding="utf-8")
    baseline_ready = research.index("Trusted baseline ready")
    identity_recovery = research.index("phase=identity-recovery")
    launch = research.index("Launching ShinkaEvolve attempt")

    assert "shinka-yukon-skill.sha256" in research
    assert 'test -s "$yukon_skill_path"' in research
    assert 'SHINKA_YUKON_SKILL_PATH="$yukon_skill_path"' in research
    assert "BEGIN INSTALLED YUKON AGENT SKILL" in run_evo
    assert 'candidate_git_user_name="${SHINKA_GIT_USER_NAME:-Amal-David}"' in research
    assert "Amal-David@users.noreply.github.com" in research
    assert "blocked-missing-git-identity" in research
    assert "identity-recovery" in research
    assert 'submit_min_bips="${SHINKA_SUBMIT_MIN_BIPS:--250}"' in research
    assert "shinka-submission-policy" in research
    assert baseline_ready < identity_recovery < launch


def test_submission_probe_attributes_harness_and_retries_local_cli_failures() -> None:
    probe = SUBMIT_PROBE.read_text(encoding="utf-8")

    assert "readonly harness='ShinkaEvolve'" in probe
    assert '--harness "$harness"' in probe
    assert 'status == "reserved" || status == "exit_0"' in probe
    assert 'last[fingerprint] == "reserved" || last[fingerprint] == "exit_0"' in probe
    assert 'if [ "$status" -eq 0 ]; then' in probe
    assert 'rm -f "$last_submit_file"' in probe
    assert "SHINKA_SUBMISSION_COOLDOWN_SECONDS=0" in RESEARCH.read_text(
        encoding="utf-8"
    )
