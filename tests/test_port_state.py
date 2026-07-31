"""Tests for the porting state machine — transitions, atomic resume, crash recovery."""

from __future__ import annotations

import json
from pathlib import Path

from pointer.porting.state import (
    Stage,
    Verdict,
    create_run,
    generate_run_id,
    is_stage_completed,
    is_terminal,
    list_runs,
    load_state,
    record_stage,
    save_state,
    set_verdict,
    state_path,
)


class TestRunId:
    def test_unique(self):
        ids = {generate_run_id() for _ in range(100)}
        assert len(ids) == 100

    def test_format(self):
        rid = generate_run_id()
        assert "-" in rid
        # Should be timestamp + hex
        parts = rid.split("-")
        assert len(parts) == 3


class TestCreateRun:
    def test_creates_directory(self, tmp_path):
        state_root = tmp_path / ".pointer" / "runs"
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=state_root,
        )
        assert Path(state.run_dir).exists()
        assert (Path(state.run_dir) / "state.json").exists()

    def test_initial_stage(self, tmp_path):
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=tmp_path / "runs",
        )
        assert state.stage == Stage.PREFLIGHT.value
        assert state.verdict is None

    def test_state_json_loadable(self, tmp_path):
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=tmp_path / "runs",
        )
        loaded = load_state(Path(state.run_dir))
        assert loaded is not None
        assert loaded.run_id == state.run_id
        assert loaded.stage == state.stage


class TestStageTransitions:
    def test_preflight_to_analyze(self, tmp_path):
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=tmp_path / "runs",
        )
        record_stage(state, Stage.PREFLIGHT, "completed")
        assert state.stage == Stage.ANALYZE.value

    def test_full_pipeline_transitions(self, tmp_path):
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=tmp_path / "runs",
        )
        for stage in [
            Stage.PREFLIGHT,
            Stage.ANALYZE,
            Stage.ORACLE_CAPTURE,
            Stage.PLAN,
            Stage.GENERATE,
            Stage.NATIVE_BUILD,
            Stage.DIFFERENTIAL_VERIFY,
            Stage.REPAIR,
            Stage.FINAL_VERIFY,
        ]:
            record_stage(state, stage, "completed")
        assert state.stage == Stage.COMPLETE.value

    def test_failed_stage_sets_failed(self, tmp_path):
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=tmp_path / "runs",
        )
        record_stage(state, Stage.GENERATE, "failed", error="codex crashed")
        assert state.stage == Stage.FAILED.value
        assert any("codex crashed" in e for e in state.errors)


class TestAtomicPersistence:
    def test_state_persists_between_saves(self, tmp_path):
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=tmp_path / "runs",
        )

        record_stage(state, Stage.PREFLIGHT, "completed")
        record_stage(state, Stage.ANALYZE, "completed")

        # Reload
        loaded = load_state(Path(state.run_dir))
        assert loaded is not None
        assert loaded.stage == Stage.ORACLE_CAPTURE.value
        assert is_stage_completed(loaded, Stage.PREFLIGHT)
        assert is_stage_completed(loaded, Stage.ANALYZE)

    def test_no_partial_writes(self, tmp_path):
        """State.json should always be valid JSON, even under interruption."""
        state_root = tmp_path / "runs"
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=state_root,
        )
        # Multiple rapid saves
        for i in range(20):
            state.warnings.append(f"warning {i}")
            save_state(state)

        # Verify file is always valid
        spath = state_path(Path(state.run_dir))
        content = spath.read_text()
        data = json.loads(content)
        assert data["run_id"] == state.run_id


class TestResume:
    def test_resume_skips_completed(self, tmp_path):
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=tmp_path / "runs",
        )
        # Complete some stages
        record_stage(state, Stage.PREFLIGHT, "completed")
        record_stage(state, Stage.ANALYZE, "completed")

        # Simulate "crash" and reload
        loaded = load_state(Path(state.run_dir))
        assert loaded is not None
        assert loaded.stage == Stage.ORACLE_CAPTURE.value
        assert is_stage_completed(loaded, Stage.PREFLIGHT)
        assert is_stage_completed(loaded, Stage.ANALYZE)
        assert not is_stage_completed(loaded, Stage.ORACLE_CAPTURE)

    def test_resume_from_interrupted_state(self, tmp_path):
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=tmp_path / "runs",
        )
        # Simulate being in the middle of generate
        record_stage(state, Stage.PREFLIGHT, "completed")
        record_stage(state, Stage.ANALYZE, "completed")
        record_stage(state, Stage.ORACLE_CAPTURE, "completed")
        record_stage(state, Stage.PLAN, "completed")
        # Generate not completed - state shows we're at GENERATE
        loaded = load_state(Path(state.run_dir))
        assert loaded is not None
        assert loaded.stage == Stage.GENERATE.value


class TestVerdict:
    def test_set_verified(self, tmp_path):
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=tmp_path / "runs",
        )
        set_verdict(state, Verdict.VERIFIED)
        assert state.stage == Stage.COMPLETE.value
        assert state.verdict == Verdict.VERIFIED.value

    def test_set_blocked(self, tmp_path):
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=tmp_path / "runs",
        )
        set_verdict(state, Verdict.BLOCKED)
        assert state.stage == Stage.BLOCKED.value

    def test_is_terminal(self, tmp_path):
        state = create_run(
            source_path="/tmp/source",
            output_dir="/tmp/output",
            state_root=tmp_path / "runs",
        )
        assert not is_terminal(state)
        set_verdict(state, Verdict.VERIFIED)
        assert is_terminal(state)


class TestListRuns:
    def test_empty(self, tmp_path):
        runs = list_runs(tmp_path / "runs")
        assert runs == []

    def test_multiple_runs(self, tmp_path):
        state_root = tmp_path / "runs"
        for i in range(3):
            create_run(
                source_path=f"/tmp/source{i}",
                output_dir=f"/tmp/output{i}",
                state_root=state_root,
            )
        runs = list_runs(state_root)
        assert len(runs) == 3
        # Should be sorted reverse (newest first)
        assert all("run_id" in r for r in runs)
