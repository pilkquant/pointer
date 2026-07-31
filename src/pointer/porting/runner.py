"""Port runner — orchestrates the full porting pipeline.

Implements the stage pipeline:
  preflight -> analyze -> oracle_capture -> plan -> generate ->
  native_build -> differential_verify -> [repair loop] -> final_verify -> complete

Each stage is resumable. Completed stages with side-effects are not repeated.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import __version__
from ..models import Target
from ..pipeline import analyze as static_analyze
from .backend import AgentBackend, get_backend
from .config import PortConfig, load_config
from .evidence import Verdict as ReportVerdict
from .evidence import build_verdict, write_json_report, write_markdown_report
from .native import NativeBuildResult, run_full_build_pipeline
from .oracle import (
    DifferentialResult,
    OracleCaptureResult,
    capture_oracle,
    verify_against_rust,
)
from .prompts import build_generation_prompt, build_repair_prompt, write_prompt_to_file
from .security import require_consent
from .state import (
    PortState,
    Stage,
    Verdict,
    create_run,
    is_stage_completed,
    is_terminal,
    load_state,
    record_stage,
    save_state,
    set_verdict,
)


@dataclass
class PortResult:
    """Final result of a porting run."""

    state: PortState
    verdict: str
    success: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.state.run_id,
            "verdict": self.verdict,
            "success": self.success,
            "message": self.message,
        }


class PortRunner:
    """Orchestrates the full porting pipeline."""

    def __init__(
        self,
        source_path: str,
        *,
        target_lang: str = "rust",
        agent_name: str = "codex",
        state_root: Path | None = None,
        output_parent: Path | None = None,
        allow_source_execution: bool = False,
        auto_yes: bool = False,
        max_repairs: int = 3,
        agent_kwargs: dict[str, Any] | None = None,
    ):
        self.source_path = Path(source_path).resolve()
        self.target_lang = target_lang
        self.agent_name = agent_name
        self.state_root = state_root or Path.cwd() / ".pointer" / "runs"
        self.output_parent = output_parent or Path.cwd() / ".pointer" / "output"
        self.allow_source_execution = allow_source_execution
        self.auto_yes = auto_yes
        self.max_repairs = max_repairs
        self.agent_kwargs = agent_kwargs or {}

        # State and config
        self.state: PortState | None = None
        self.config: PortConfig | None = None
        self.backend: AgentBackend | None = None
        self.oracle_result: OracleCaptureResult | None = None
        self.build_result: NativeBuildResult | None = None
        self.verify_result: DifferentialResult | None = None
        self.analysis_json: dict[str, Any] | None = None

    def _ensure_state(self) -> PortState:
        """Create or load state."""
        if self.state is None:
            output_dir = self.output_parent / "latest"
            self.state = create_run(
                source_path=str(self.source_path),
                output_dir=str(output_dir),
                state_root=self.state_root,
                target_lang=self.target_lang,
                agent_backend=self.agent_name,
                allow_source_execution=self.allow_source_execution,
                auto_yes=self.auto_yes,
                max_repairs=self.max_repairs,
                pointer_version=__version__,
            )
            # Create the actual output directory for this run
            run_output = self.output_parent / self.state.run_id
            run_output.mkdir(parents=True, exist_ok=True)
            self.state.output_dir = str(run_output)
            save_state(self.state)
        return self.state

    def _get_backend(self) -> AgentBackend:
        """Get or create the agent backend."""
        if self.backend is None:
            self.backend = get_backend(self.agent_name, **self.agent_kwargs)
        return self.backend

    def run(self) -> PortResult:
        """Execute the full pipeline, resuming if needed."""
        state = self._ensure_state()

        while not is_terminal(state):  # type: ignore[arg-type]
            current = Stage(state.stage)  # type: ignore[union-attr]

            if current == Stage.PREFLIGHT:
                self._stage_preflight()
            elif current == Stage.ANALYZE:
                self._stage_analyze()
            elif current == Stage.ORACLE_CAPTURE:
                self._stage_oracle_capture()
            elif current == Stage.PLAN:
                self._stage_plan()
            elif current == Stage.GENERATE:
                self._stage_generate()
            elif current == Stage.NATIVE_BUILD:
                self._stage_native_build()
            elif current == Stage.DIFFERENTIAL_VERIFY:
                self._stage_differential_verify()
            elif current == Stage.REPAIR:
                self._stage_repair()
            elif current == Stage.FINAL_VERIFY:
                self._stage_final_verify()
            elif current == Stage.COMPLETE:
                break
            else:
                # Terminal state
                break

            state = self.state  # Refresh

        # If we hit a terminal failure/blocked state, write evidence reports
        # so the user always gets a report even on early failures.
        assert state is not None
        if state.stage != Stage.COMPLETE.value and is_terminal(state):
            from .evidence import write_json_report, write_markdown_report

            run_dir = Path(state.run_dir)
            write_json_report(state, run_dir)
            write_markdown_report(state, run_dir)

        return self._build_result()

    # --- Stage implementations ---

    def _stage_preflight(self) -> None:
        """Stage 1: validate environment and inputs."""
        state = self.state
        assert state is not None
        start = time.monotonic()

        errors: list[str] = []

        # Check source exists
        if not self.source_path.exists():
            errors.append(f"Source path does not exist: {self.source_path}")
        elif not self.source_path.is_dir():
            errors.append(f"Source path is not a directory: {self.source_path}")

        # Load config
        try:
            self.config = load_config(self.source_path)
        except Exception as e:
            self.config = None
            state.warnings.append(f"Failed to load pointer.toml: {e}")

        # Probe backend
        backend = self._get_backend()
        caps = backend.probe()
        state.agent_backend_version = caps.version

        if not caps.available:
            errors.append(f"Agent backend unavailable: {caps.error}")
        elif not caps.authenticated:
            state.warnings.append(f"Agent backend not authenticated: {caps.version}")

        if errors:
            record_stage(state, Stage.PREFLIGHT, "failed", duration=time.monotonic() - start, error="; ".join(errors))
            set_verdict(state, Verdict.BLOCKED)
            return

        record_stage(
            state,
            Stage.PREFLIGHT,
            "completed",
            duration=time.monotonic() - start,
            evidence={"backend_version": caps.version, "backend_authed": caps.authenticated},
        )

    def _stage_analyze(self) -> None:
        """Stage 2: run v0.1 static analysis."""
        state = self.state
        assert state is not None
        start = time.monotonic()

        try:
            report = static_analyze(self.source_path, Target.RUST)
            # Serialize to dict for storage/prompt
            from ..report.json_out import _serialize

            self.analysis_json = _serialize(report)
        except Exception as e:
            record_stage(state, Stage.ANALYZE, "failed", duration=time.monotonic() - start, error=str(e))
            set_verdict(state, Verdict.FAILED)
            return

        record_stage(
            state,
            Stage.ANALYZE,
            "completed",
            duration=time.monotonic() - start,
            evidence={"analysis_summary": report.summary[:200]},
        )

    def _stage_oracle_capture(self) -> None:
        """Stage 3: capture Python oracle outputs."""
        state = self.state
        assert state is not None
        start = time.monotonic()

        if not self.config or not self.config.oracle_cases:
            # No oracle cases configured
            state.warnings.append("No oracle cases configured. Port cannot be verified.")
            record_stage(
                state,
                Stage.ORACLE_CAPTURE,
                "completed",
                duration=time.monotonic() - start,
                evidence={"total_cases": 0, "reason": "no pointer.toml oracle cases"},
            )
            return

        # Check consent
        consent = require_consent(
            has_consent=self.allow_source_execution,
            auto_yes=self.auto_yes,
        )
        state.consent_given = consent

        if not consent:
            state.warnings.append(
                "Source execution consent not given. Oracle cannot be captured. Use --allow-source-execution to enable."
            )
            record_stage(
                state,
                Stage.ORACLE_CAPTURE,
                "completed",
                duration=time.monotonic() - start,
                evidence={"total_cases": 0, "reason": "consent not given"},
            )
            return

        try:
            self.oracle_result = capture_oracle(
                cases=self.config.oracle_cases,
                source_root=self.source_path,
                normalization=self.config.normalization,
                consent_given=True,
                network_isolated=False,
            )
            state.oracle_cases = [c.to_dict() for c in self.config.oracle_cases]
        except PermissionError as e:
            record_stage(state, Stage.ORACLE_CAPTURE, "failed", duration=time.monotonic() - start, error=str(e))
            set_verdict(state, Verdict.BLOCKED)
            return
        except Exception as e:
            record_stage(state, Stage.ORACLE_CAPTURE, "failed", duration=time.monotonic() - start, error=str(e))
            set_verdict(state, Verdict.FAILED)
            return

        record_stage(
            state,
            Stage.ORACLE_CAPTURE,
            "completed",
            duration=time.monotonic() - start,
            evidence=self.oracle_result.to_dict(),
        )

    def _stage_plan(self) -> None:
        """Stage 4: build the generation prompt."""
        state = self.state
        assert state is not None
        start = time.monotonic()

        output_dir = Path(state.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        prompt = build_generation_prompt(
            source_root=self.source_path,
            port_config=self.config or PortConfig(),
            oracle_result=self.oracle_result,
            analysis_json=self.analysis_json,
            output_dir=output_dir,
        )

        # Save prompt for inspection
        prompt_path = write_prompt_to_file(prompt, Path(state.run_dir), "generate")
        state.warnings.append(f"Generation prompt saved to {prompt_path}")

        record_stage(
            state,
            Stage.PLAN,
            "completed",
            duration=time.monotonic() - start,
            evidence={"prompt_path": str(prompt_path), "prompt_chars": len(prompt)},
        )

    def _stage_generate(self) -> None:
        """Stage 5: agent generates Rust workspace."""
        state = self.state
        assert state is not None
        start = time.monotonic()

        output_dir = Path(state.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load the saved prompt
        prompt_path = Path(state.run_dir) / "prompt-generate.md"
        prompt = prompt_path.read_text(encoding="utf-8")

        backend = self._get_backend()
        result = backend.generate(prompt, output_dir, timeout=600.0)

        state.agent_session_id = result.session_id
        state.agent_thread_id = result.thread_id

        if not result.success:
            record_stage(
                state,
                Stage.GENERATE,
                "failed",
                duration=time.monotonic() - start,
                error=result.error,
                evidence={"exit_code": result.exit_code},
            )
            set_verdict(state, Verdict.FAILED)
            return

        record_stage(
            state,
            Stage.GENERATE,
            "completed",
            duration=time.monotonic() - start,
            evidence={
                "session_id": result.session_id,
                "last_message": result.last_message[:200],
                "duration": result.duration_seconds,
            },
        )

    def _stage_native_build(self) -> None:
        """Stage 6: build and test the generated Rust."""
        state = self.state
        assert state is not None
        start = time.monotonic()

        output_dir = Path(state.output_dir)

        self.build_result = run_full_build_pipeline(output_dir, timeout=300.0)

        if self.build_result.binary_path:
            state.native_binary_path = str(self.build_result.binary_path)
        if self.build_result.binary_hash:
            state.native_artifact_hash = self.build_result.binary_hash

        if not self.build_result.all_passed:
            record_stage(
                state,
                Stage.NATIVE_BUILD,
                "completed",
                duration=time.monotonic() - start,
                evidence=self.build_result.to_dict(),
            )
            # Don't fail — move to repair stage
            return

        record_stage(
            state,
            Stage.NATIVE_BUILD,
            "completed",
            duration=time.monotonic() - start,
            evidence=self.build_result.to_dict(),
        )

    def _stage_differential_verify(self) -> None:
        """Stage 7: differential verification against oracle."""
        state = self.state
        assert state is not None
        start = time.monotonic()

        # If no oracle or no binary, skip
        if not self.oracle_result or not self.oracle_result.cases:
            record_stage(
                state,
                Stage.DIFFERENTIAL_VERIFY,
                "completed",
                duration=time.monotonic() - start,
                evidence={"reason": "no oracle cases"},
            )
            return

        if not self.build_result or not self.build_result.binary_path:
            record_stage(
                state,
                Stage.DIFFERENTIAL_VERIFY,
                "completed",
                duration=time.monotonic() - start,
                evidence={"reason": "no binary built"},
            )
            return

        assert self.config is not None

        self.verify_result = verify_against_rust(
            cases=self.config.oracle_cases,
            oracle_results=self.oracle_result.cases,
            rust_binary=self.build_result.binary_path,
            normalization=self.config.normalization,
        )

        state.verification_results = self.verify_result.results
        state.all_cases_passed = self.verify_result.all_passed

        record_stage(
            state,
            Stage.DIFFERENTIAL_VERIFY,
            "completed",
            duration=time.monotonic() - start,
            evidence=self.verify_result.to_dict(),
        )

    def _stage_repair(self) -> None:
        """Stage 8: bounded repair loop."""
        state = self.state
        assert state is not None
        start = time.monotonic()

        # Check if repair is needed
        needs_repair = False
        if self.build_result and not self.build_result.all_passed:
            needs_repair = True
        if self.verify_result and not self.verify_result.all_passed:
            needs_repair = True

        if not needs_repair:
            record_stage(
                state,
                Stage.REPAIR,
                "completed",
                duration=time.monotonic() - start,
                evidence={"repairs_done": state.repair_count, "needed": False},
            )
            return

        # Repair budget check
        if state.repair_count >= state.max_repairs:
            state.warnings.append(f"Repair budget exhausted ({state.repair_count}/{state.max_repairs})")
            record_stage(
                state,
                Stage.REPAIR,
                "completed",
                duration=time.monotonic() - start,
                evidence={"repairs_done": state.repair_count, "exhausted": True},
            )
            return

        # Build repair prompt
        repair_prompt = build_repair_prompt(
            build_result=self.build_result.to_dict() if self.build_result else {},
            verification_result=self.verify_result.to_dict() if self.verify_result else None,
            repair_attempt=state.repair_count + 1,
            max_repairs=state.max_repairs,
        )
        write_prompt_to_file(repair_prompt, Path(state.run_dir), f"repair-{state.repair_count + 1}")

        # Execute repair
        backend = self._get_backend()
        output_dir = Path(state.output_dir)
        result = backend.repair(
            repair_prompt,
            output_dir,
            session_id=state.agent_session_id,
            timeout=600.0,
        )

        state.repair_count += 1
        repair_entry: dict[str, Any] = {
            "attempt": state.repair_count,
            "success": result.success,
            "session_id": result.session_id,
            "error": result.error,
            "last_message": result.last_message[:200],
        }
        state.repair_history.append(repair_entry)

        if result.success:
            # Re-run build after repair
            self.build_result = run_full_build_pipeline(output_dir, timeout=300.0)
            if self.build_result.binary_path:
                state.native_binary_path = str(self.build_result.binary_path)
            if self.build_result.binary_hash:
                state.native_artifact_hash = self.build_result.binary_hash

            # Re-run verification if we have oracle
            if self.oracle_result and self.oracle_result.cases and self.config:
                if self.build_result.binary_path:
                    self.verify_result = verify_against_rust(
                        cases=self.config.oracle_cases,
                        oracle_results=self.oracle_result.cases,
                        rust_binary=self.build_result.binary_path,
                        normalization=self.config.normalization,
                    )
                    state.verification_results = self.verify_result.results
                    state.all_cases_passed = self.verify_result.all_passed

        repair_entry["build_passed"] = self.build_result.all_passed if self.build_result else False
        repair_entry["verify_passed"] = self.verify_result.all_passed if self.verify_result else False
        # Update the last entry
        state.repair_history[-1] = repair_entry

        save_state(state)

        record_stage(
            state,
            Stage.REPAIR,
            "completed",
            duration=time.monotonic() - start,
            evidence={"repairs_done": state.repair_count},
        )

        # After recording (which advanced stage to final_verify), check
        # whether another repair cycle is needed and budget remains.
        # If so, loop back to native_build for another build→verify→repair cycle.
        still_needs_repair = (self.build_result and not self.build_result.all_passed) or (
            self.verify_result and not self.verify_result.all_passed
        )
        if still_needs_repair and state.repair_count < state.max_repairs:
            state.stage = Stage.NATIVE_BUILD.value
            save_state(state)

    def _stage_final_verify(self) -> None:
        """Stage 9: final verification and verdict."""
        state = self.state
        assert state is not None
        start = time.monotonic()

        # Determine final verdict
        native_passed = self.build_result is not None and self.build_result.all_passed
        cases_passed = self.verify_result.all_passed if self.verify_result else False
        has_oracle = (
            self.oracle_result is not None
            and len(self.oracle_result.cases) > 0
            and self.oracle_result.successful_captures > 0
        )
        generation_ok = is_stage_completed(state, Stage.GENERATE)

        verdict = build_verdict(
            state,
            native_build_passed=native_passed,
            all_cases_passed=cases_passed,
            has_oracle=has_oracle,
            generation_succeeded=generation_ok,
        )

        # Map evidence.Verdict -> state.Verdict
        verdict_map = {
            ReportVerdict.VERIFIED: Verdict.VERIFIED,
            ReportVerdict.GENERATED_UNVERIFIED: Verdict.GENERATED_UNVERIFIED,
            ReportVerdict.BLOCKED: Verdict.BLOCKED,
            ReportVerdict.FAILED: Verdict.FAILED,
            ReportVerdict.CANCELLED: Verdict.CANCELLED,
        }

        # Set verdict first, THEN write reports so they see the correct verdict
        final_verdict = verdict_map.get(verdict, Verdict.GENERATED_UNVERIFIED)
        set_verdict(state, final_verdict)

        # Write evidence reports (after verdict is set on state)
        run_dir = Path(state.run_dir)
        write_json_report(state, run_dir)
        write_markdown_report(state, run_dir)

        record_stage(
            state,
            Stage.FINAL_VERIFY,
            "completed",
            duration=time.monotonic() - start,
            evidence={"verdict": verdict.value},
        )

    def _build_result(self) -> PortResult:
        """Build the final result object."""
        state = self.state
        assert state is not None

        verdict = state.verdict or Verdict.FAILED.value
        success = verdict == Verdict.VERIFIED.value

        if success:
            message = f"Port verified: {state.run_id}"
        elif verdict == Verdict.GENERATED_UNVERIFIED.value:
            message = f"Generated but unverified: {state.run_id}"
        elif verdict == Verdict.BLOCKED.value:
            message = f"Blocked: {state.run_id}"
        else:
            message = f"Failed: {state.run_id}"

        return PortResult(
            state=state,
            verdict=verdict,
            success=success,
            message=message,
        )


def resume_run(run_id: str, state_root: Path) -> PortResult:
    """Resume an interrupted run by ID."""
    from .state import run_directory

    run_dir = run_directory(state_root, run_id)
    state = load_state(run_dir)
    if state is None:
        raise ValueError(f"Run not found: {run_id}")

    runner = PortRunner(
        source_path=state.source_path,
        target_lang=state.target_lang,
        agent_name=state.agent_backend,
        state_root=state_root,
        output_parent=Path(state.output_dir).parent,
        allow_source_execution=state.allow_source_execution,
        auto_yes=state.auto_yes,
        max_repairs=state.max_repairs,
    )
    runner.state = state
    return runner.run()
