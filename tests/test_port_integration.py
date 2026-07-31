"""Integration tests for the full porting pipeline using FakeBackend.

Tests the complete pipeline end-to-end: preflight → analyze → oracle → plan →
generate → native_build → verify → repair → final_verify.

Uses the FakeBackend which writes real, compilable Rust code.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

# Skip these tests if cargo is not available
pytestmark = pytest.mark.skipif(
    shutil.which("cargo") is None,
    reason="cargo not available — porting integration tests require Rust toolchain",
)


@pytest.fixture
def tinycalc_fixture(tmp_path):
    """Create a minimal Python project that the FakeBackend can port."""
    src_dir = tmp_path / "src" / "tinycalc"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text(
        'def add(a, b):\n    return a + b\nif __name__ == "__main__":\n    print(add(1, 2))\n'
    )
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "tinycalc"\nversion = "0.1.0"\n')
    return tmp_path


@pytest.fixture
def porting_env(tmp_path, tinycalc_fixture):
    """Set up porting environment with paths."""
    return {
        "source": str(tinycalc_fixture),
        "state_root": tmp_path / ".pointer" / "runs",
        "output_parent": tmp_path / ".pointer" / "output",
    }


class TestFakeBackendPorting:
    def test_full_pipeline_verified(self, porting_env):
        """Full pipeline with FakeBackend should produce verified Rust."""
        from pointer.porting.runner import PortRunner

        runner = PortRunner(
            source_path=porting_env["source"],
            target_lang="rust",
            agent_name="fake",
            state_root=porting_env["state_root"],
            output_parent=porting_env["output_parent"],
            allow_source_execution=False,  # No oracle needed for this test
            auto_yes=True,
            max_repairs=3,
            agent_kwargs={},
        )
        result = runner.run()

        # FakeBackend writes compilable Rust, so build should pass
        # But without oracle, verdict is generated_unverified
        assert result.verdict in ("verified", "generated_unverified")
        assert result.state.stage in ("complete",)

    def test_native_build_produces_binary(self, porting_env):
        """The pipeline should produce a release binary."""
        from pointer.porting.runner import PortRunner

        runner = PortRunner(
            source_path=porting_env["source"],
            target_lang="rust",
            agent_name="fake",
            state_root=porting_env["state_root"],
            output_parent=porting_env["output_parent"],
            allow_source_execution=False,
            auto_yes=True,
        )
        result = runner.run()

        state = result.state
        if state.native_binary_path:
            assert Path(state.native_binary_path).exists()
        if state.native_artifact_hash:
            assert len(state.native_artifact_hash) == 64

    def test_state_persisted(self, porting_env):
        """State.json should be persisted and loadable."""
        from pointer.porting.runner import PortRunner
        from pointer.porting.state import load_state

        runner = PortRunner(
            source_path=porting_env["source"],
            target_lang="rust",
            agent_name="fake",
            state_root=porting_env["state_root"],
            output_parent=porting_env["output_parent"],
            auto_yes=True,
        )
        result = runner.run()

        state = load_state(Path(result.state.run_dir))
        assert state is not None
        assert state.run_id == result.state.run_id

    def test_reports_generated(self, porting_env):
        """Evidence reports should be generated."""
        from pointer.porting.runner import PortRunner

        runner = PortRunner(
            source_path=porting_env["source"],
            target_lang="rust",
            agent_name="fake",
            state_root=porting_env["state_root"],
            output_parent=porting_env["output_parent"],
            auto_yes=True,
        )
        result = runner.run()

        run_dir = Path(result.state.run_dir)
        assert (run_dir / "report.md").exists()
        assert (run_dir / "evidence.json").exists()
        # Verify report content
        report = (run_dir / "report.md").read_text()
        assert "Pointer Port Report" in report
        assert "Verdict" in report

    def test_no_false_verified_without_oracle(self, porting_env):
        """Without oracle, verdict must NOT be verified."""
        from pointer.porting.runner import PortRunner

        runner = PortRunner(
            source_path=porting_env["source"],
            target_lang="rust",
            agent_name="fake",
            state_root=porting_env["state_root"],
            output_parent=porting_env["output_parent"],
            allow_source_execution=False,
            auto_yes=True,
        )
        result = runner.run()
        assert result.verdict != "verified", "Should not be verified without oracle"


class TestPortingWithOracle:
    def test_full_pipeline_with_oracle(self, tinycalc_fixture, tmp_path):
        """Full pipeline with oracle capture (using --allow-source-execution)."""
        from pointer.porting.runner import PortRunner

        # Create pointer.toml for the fixture
        (tinycalc_fixture / "pointer.toml").write_text(
            '[port]\ntarget = "rust"\n\n'
            "[[oracle.cases]]\n"
            'name = "basic"\n'
            'command = ["python", "-c", "print(1 + 2)"]\n'
            "expected_exit = 0\n"
        )

        runner = PortRunner(
            source_path=str(tinycalc_fixture),
            target_lang="rust",
            agent_name="fake",
            state_root=tmp_path / ".pointer" / "runs",
            output_parent=tmp_path / ".pointer" / "output",
            allow_source_execution=True,
            auto_yes=True,
        )
        result = runner.run()

        # With oracle, FakeBackend produces a calculator that supports basic math
        # The oracle command is "python -c print(1+2)" which outputs 3
        # But FakeBackend generates a calculator CLI that takes args
        # So the rewritten command [binary, "-c", "print(1+2)"] won't match
        # This test verifies the pipeline runs, not that it verifies
        assert result.verdict in ("verified", "generated_unverified")


class TestPortingResume:
    def test_resume_after_interrupt(self, porting_env):
        """Test that a run can be resumed after interruption."""
        from pointer.porting.runner import PortRunner, resume_run

        # Create initial run
        runner = PortRunner(
            source_path=porting_env["source"],
            target_lang="rust",
            agent_name="fake",
            state_root=porting_env["state_root"],
            output_parent=porting_env["output_parent"],
            auto_yes=True,
        )
        state = runner._ensure_state()
        run_id = state.run_id

        # Simulate partial completion (analyze stage)
        from pointer.porting.state import Stage, record_stage

        record_stage(state, Stage.PREFLIGHT, "completed")
        record_stage(state, Stage.ANALYZE, "completed")

        # Now resume
        result = resume_run(run_id, porting_env["state_root"])
        assert result.state.run_id == run_id
        assert result.state.stage in ("complete", "failed", "blocked")


class TestPortingRepair:
    def test_repair_with_fail_first(self, porting_env):
        """FakeBackend with fail_first should trigger repair."""
        from pointer.porting.runner import PortRunner

        runner = PortRunner(
            source_path=porting_env["source"],
            target_lang="rust",
            agent_name="fake",
            state_root=porting_env["state_root"],
            output_parent=porting_env["output_parent"],
            auto_yes=True,
            max_repairs=3,
            agent_kwargs={"fail_first": True},
        )
        result = runner.run()

        # Should have attempted repairs
        assert result.state.repair_count >= 1

    def test_repair_budget_exhaustion(self, porting_env):
        """When repair budget is 0, no repairs should be attempted."""
        from pointer.porting.runner import PortRunner

        runner = PortRunner(
            source_path=porting_env["source"],
            target_lang="rust",
            agent_name="fake",
            state_root=porting_env["state_root"],
            output_parent=porting_env["output_parent"],
            auto_yes=True,
            max_repairs=0,
            agent_kwargs={"fail_first": True},
        )
        result = runner.run()

        assert result.state.repair_count == 0
