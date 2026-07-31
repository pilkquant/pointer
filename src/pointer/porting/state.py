"""Porting run state machine — durable, atomic, resumable.

Each porting run is persisted under ``.pointer/runs/<run-id>/state.json`` and
follows an explicit stage pipeline:

  preflight -> analyze -> oracle_capture -> plan -> generate ->
  native_build -> differential_verify -> [repair loop] -> final_verify ->
  complete | blocked | failed

State writes are atomic (temp file + rename). Interrupted runs resume by
checking ``stage`` and skipping already-completed stages. Stages that involve
side-effects (oracle capture, agent generation, native build) are tracked with
a completion flag so they are never repeated on resume.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

STATE_SCHEMA_VERSION = "1"


class Stage(StrEnum):
    """Porting pipeline stages in order."""

    PREFLIGHT = "preflight"
    ANALYZE = "analyze"
    ORACLE_CAPTURE = "oracle_capture"
    PLAN = "plan"
    GENERATE = "generate"
    NATIVE_BUILD = "native_build"
    DIFFERENTIAL_VERIFY = "differential_verify"
    REPAIR = "repair"
    FINAL_VERIFY = "final_verify"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    FAILED = "failed"


# Ordered stages for the normal pipeline flow
_PIPELINE_ORDER = [
    Stage.PREFLIGHT,
    Stage.ANALYZE,
    Stage.ORACLE_CAPTURE,
    Stage.PLAN,
    Stage.GENERATE,
    Stage.NATIVE_BUILD,
    Stage.DIFFERENTIAL_VERIFY,
    Stage.REPAIR,
    Stage.FINAL_VERIFY,
    Stage.COMPLETE,
]


class Verdict(StrEnum):
    """Final verdict for a porting run."""

    VERIFIED = "verified"
    GENERATED_UNVERIFIED = "generated_unverified"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StageOutcome:
    """Recorded outcome for a single stage execution."""

    stage: str
    status: str  # "completed", "skipped", "failed", "in_progress"
    started_at: str = ""
    completed_at: str = ""
    exit_code: int | None = None
    duration_seconds: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class PortState:
    """Durable state for a single porting run.

    All fields are JSON-serialisable. State is written atomically to
    ``state.json`` under the run directory.
    """

    run_id: str
    schema_version: str = STATE_SCHEMA_VERSION
    source_path: str = ""
    target_lang: str = "rust"
    agent_backend: str = "codex"
    stage: str = Stage.PREFLIGHT.value
    verdict: str | None = None
    created_at: str = ""
    updated_at: str = ""
    # Paths
    output_dir: str = ""
    run_dir: str = ""
    # Configuration
    allow_source_execution: bool = False
    auto_yes: bool = False
    max_repairs: int = 3
    # Oracle
    oracle_cases: list[dict[str, Any]] = field(default_factory=list)
    # Agent
    agent_session_id: str | None = None
    agent_thread_id: str | None = None
    agent_backend_version: str = ""
    # Stage outcomes (keyed by stage name)
    stage_outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Repair tracking
    repair_count: int = 0
    repair_history: list[dict[str, Any]] = field(default_factory=list)
    # Native build
    native_binary_path: str | None = None
    native_artifact_hash: str | None = None
    # Differential verification
    verification_results: list[dict[str, Any]] = field(default_factory=list)
    all_cases_passed: bool = False
    # Security
    consent_given: bool = False
    network_isolated: bool = False
    # Misc
    pointer_version: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortState:
        """Deserialize from a dict (tolerates missing fields)."""
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def _now() -> str:
    """ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def generate_run_id() -> str:
    """Generate a short unique run ID."""
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)


def default_state_root(base: Path | None = None) -> Path:
    """Return the default state root directory.

    Uses POINTER_STATE_ROOT env var if set, otherwise ``.pointer/runs``
    under the given base path (or cwd).
    """
    env_root = os.environ.get("POINTER_STATE_ROOT")
    if env_root:
        return Path(env_root)
    return (base or Path.cwd()) / ".pointer" / "runs"


def run_directory(state_root: Path, run_id: str) -> Path:
    """Return the directory path for a specific run."""
    return state_root / run_id


def create_run(
    source_path: str,
    output_dir: str,
    state_root: Path,
    *,
    target_lang: str = "rust",
    agent_backend: str = "codex",
    allow_source_execution: bool = False,
    auto_yes: bool = False,
    max_repairs: int = 3,
    pointer_version: str = "",
    run_id: str | None = None,
) -> PortState:
    """Create a new porting run with initial state."""
    run_id = run_id or generate_run_id()
    run_dir = run_directory(state_root, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    output_dir_abs = str(Path(output_dir).resolve())

    state = PortState(
        run_id=run_id,
        source_path=str(Path(source_path).resolve()),
        target_lang=target_lang,
        agent_backend=agent_backend,
        stage=Stage.PREFLIGHT.value,
        created_at=_now(),
        updated_at=_now(),
        output_dir=output_dir_abs,
        run_dir=str(run_dir),
        allow_source_execution=allow_source_execution,
        auto_yes=auto_yes,
        max_repairs=max_repairs,
        pointer_version=pointer_version,
    )
    save_state(state)
    return state


def state_path(run_dir: Path | str) -> Path:
    """Return the state.json path for a run directory."""
    return Path(run_dir) / "state.json"


def save_state(state: PortState) -> None:
    """Atomically save state to ``<run_dir>/state.json``.

    Uses a temp file + os.replace for atomicity on POSIX systems.
    """
    state.updated_at = _now()
    run_dir = Path(state.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    spath = state_path(run_dir)

    data = state.to_dict()
    content = json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False)

    # Atomic write: temp file in same directory, then rename
    fd, tmp_path = tempfile.mkstemp(dir=str(run_dir), suffix=".tmp", prefix="state_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content + "\n")
        os.replace(tmp_path, spath)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_state(run_dir: Path | str) -> PortState | None:
    """Load state from ``<run_dir>/state.json``.

    Returns None if the file does not exist.
    """
    spath = state_path(run_dir)
    if not spath.exists():
        return None
    with open(spath, encoding="utf-8") as f:
        data = json.load(f)
    return PortState.from_dict(data)


def record_stage(
    state: PortState,
    stage: Stage,
    status: str,
    *,
    exit_code: int | None = None,
    duration: float = 0.0,
    evidence: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    """Record a stage outcome and advance the current stage if appropriate."""
    outcome = StageOutcome(
        stage=stage.value,
        status=status,
        started_at=state.updated_at,
        completed_at=_now(),
        exit_code=exit_code,
        duration_seconds=round(duration, 3),
        evidence=evidence or {},
        error=error,
    )
    state.stage_outcomes[stage.value] = asdict(outcome)

    if status == "completed":
        # Advance to the next pipeline stage
        _advance_stage(state, stage)
    elif status == "failed":
        state.stage = Stage.FAILED.value
        if error:
            state.errors.append(f"[{stage.value}] {error}")

    save_state(state)


def _advance_stage(state: PortState, completed: Stage) -> None:
    """Advance the state machine to the stage after ``completed``."""
    try:
        idx = _PIPELINE_ORDER.index(completed)
    except ValueError:
        # completed is a terminal state
        state.stage = completed.value
        return

    if idx + 1 < len(_PIPELINE_ORDER):
        state.stage = _PIPELINE_ORDER[idx + 1].value
    else:
        state.stage = Stage.COMPLETE.value


def is_stage_completed(state: PortState, stage: Stage) -> bool:
    """Check if a stage has a 'completed' outcome recorded."""
    outcome = state.stage_outcomes.get(stage.value)
    return outcome is not None and outcome.get("status") == "completed"


def is_terminal(state: PortState) -> bool:
    """Check if the run is in a terminal state."""
    return state.stage in (
        Stage.COMPLETE.value,
        Stage.BLOCKED.value,
        Stage.FAILED.value,
    )


def set_verdict(state: PortState, verdict: Verdict) -> None:
    """Set the final verdict for a run."""
    state.verdict = verdict.value
    if verdict == Verdict.VERIFIED:
        state.stage = Stage.COMPLETE.value
    elif verdict == Verdict.GENERATED_UNVERIFIED:
        state.stage = Stage.COMPLETE.value
    elif verdict == Verdict.BLOCKED:
        state.stage = Stage.BLOCKED.value
    elif verdict == Verdict.FAILED:
        state.stage = Stage.FAILED.value
    elif verdict == Verdict.CANCELLED:
        state.stage = Stage.FAILED.value
    save_state(state)


def list_runs(state_root: Path) -> list[dict[str, Any]]:
    """List all runs in a state root with summary info."""
    runs: list[dict[str, Any]] = []
    if not state_root.exists():
        return runs

    for entry in sorted(state_root.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        spath = entry / "state.json"
        if not spath.exists():
            continue
        try:
            state = load_state(entry)
            if state:
                runs.append(
                    {
                        "run_id": state.run_id,
                        "stage": state.stage,
                        "verdict": state.verdict,
                        "source": state.source_path,
                        "created_at": state.created_at,
                        "updated_at": state.updated_at,
                    }
                )
        except (json.JSONDecodeError, OSError):
            continue

    return runs
