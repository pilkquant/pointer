"""Evidence and report generation — human-readable markdown + machine-readable JSON.

Produces a structured verdict for every porting run. Final verdict vocabulary:
- verified: Rust builds, tests pass, all oracle cases pass
- generated_unverified: Rust generated but not verified (oracle missing or failed)
- blocked: run blocked by missing capability/consent
- failed: run failed
- cancelled: run cancelled by user
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .state import PortState, Stage, Verdict


def _serialize(obj: Any) -> Any:
    """Recursively serialize for JSON."""
    if isinstance(obj, Enum):
        return obj.value
    elif is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    elif isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    elif isinstance(obj, Path):
        return str(obj)
    elif obj is None:
        return None
    return obj


def build_verdict(
    state: PortState,
    *,
    native_build_passed: bool = False,
    all_cases_passed: bool = False,
    has_oracle: bool = False,
    generation_succeeded: bool = False,
) -> Verdict:
    """Determine the correct verdict for a run based on evidence."""
    if state.stage == Stage.FAILED.value and not generation_succeeded:
        return Verdict.FAILED

    if state.stage == Stage.BLOCKED.value:
        return Verdict.BLOCKED

    if not generation_succeeded:
        return Verdict.FAILED

    # Generation succeeded — check verification
    if has_oracle and native_build_passed and all_cases_passed:
        return Verdict.VERIFIED
    elif native_build_passed and not has_oracle:
        return Verdict.GENERATED_UNVERIFIED
    elif native_build_passed and has_oracle and not all_cases_passed:
        return Verdict.GENERATED_UNVERIFIED
    else:
        return Verdict.GENERATED_UNVERIFIED


def build_report_data(state: PortState) -> dict[str, Any]:
    """Build the complete machine-readable report data."""
    return {
        "schema_version": "1.0",
        "report_type": "porting",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run": state.to_dict(),
    }


def write_json_report(state: PortState, run_dir: Path) -> Path:
    """Write the JSON evidence report."""
    report_data = build_report_data(state)
    content = json.dumps(_serialize(report_data), indent=2, ensure_ascii=False, default=str)
    path = run_dir / "evidence.json"
    path.write_text(content + "\n", encoding="utf-8")
    return path


def write_markdown_report(state: PortState, run_dir: Path) -> Path:
    """Write the human-readable markdown evidence report."""
    lines: list[str] = []

    lines.append(f"# Pointer Port Report — {state.run_id}")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(UTC).isoformat(timespec='seconds')}")
    lines.append(f"**Pointer version:** {state.pointer_version}")
    lines.append(f"**Target language:** {state.target_lang}")
    lines.append(f"**Agent backend:** {state.agent_backend} ({state.agent_backend_version})")
    lines.append("")

    # Verdict
    verdict = state.verdict or "unknown"
    verdict_emoji = {
        Verdict.VERIFIED.value: "✅",
        Verdict.GENERATED_UNVERIFIED.value: "⚠️",
        Verdict.BLOCKED.value: "🚫",
        Verdict.FAILED.value: "❌",
        Verdict.CANCELLED.value: "⊘",
    }
    lines.append(f"## Verdict: {verdict_emoji.get(verdict, '?')} {verdict}")
    lines.append("")

    # Verdict explanation
    if verdict == Verdict.VERIFIED.value:
        lines.append(
            "The Rust port builds in release mode, passes all checks (fmt, clippy, test), "
            "and every configured oracle case passes differential verification."
        )
    elif verdict == Verdict.GENERATED_UNVERIFIED.value:
        lines.append(
            "Rust workspace was generated and may build, but verification is incomplete. This is NOT a verified port."
        )
    elif verdict == Verdict.BLOCKED.value:
        lines.append("The run is blocked. See blockers below.")
    elif verdict == Verdict.FAILED.value:
        lines.append("The run failed. See errors below.")
    lines.append("")

    # Source
    lines.append("## Source")
    lines.append(f"- Path: `{state.source_path}`")
    lines.append("")

    # Oracle
    lines.append("## Oracle")
    lines.append(f"- Execution consent: {'yes' if state.consent_given else 'NO'}")
    lines.append(f"- Network isolated: {'yes' if state.network_isolated else 'no'}")
    oracle_cases = state.stage_outcomes.get("oracle_capture", {}).get("evidence", {})
    if oracle_cases:
        lines.append(f"- Total cases: {oracle_cases.get('total_cases', 'N/A')}")
        lines.append(f"- Successful captures: {oracle_cases.get('successful_captures', 'N/A')}")
        lines.append(f"- Failed captures: {oracle_cases.get('failed_captures', 'N/A')}")
    lines.append("")

    # Stage timeline
    lines.append("## Stage Timeline")
    for stage_name in [
        "preflight",
        "analyze",
        "oracle_capture",
        "plan",
        "generate",
        "native_build",
        "differential_verify",
        "repair",
        "final_verify",
    ]:
        outcome = state.stage_outcomes.get(stage_name)
        if outcome:
            status = outcome.get("status", "?")
            duration = outcome.get("duration_seconds", 0)
            icon = "✅" if status == "completed" else "❌" if status == "failed" else "⏭️"
            lines.append(f"- {icon} {stage_name}: {status} ({duration:.1f}s)")
    lines.append("")

    # Repair
    if state.repair_count > 0:
        lines.append("## Repairs")
        lines.append(f"- Total repair attempts: {state.repair_count}")
        lines.append(f"- Budget: {state.max_repairs}")
        for entry in state.repair_history:
            attempt = entry.get("attempt", "?")
            success = entry.get("success", False)
            icon = "✅" if success else "❌"
            lines.append(f"- {icon} Attempt {attempt}: {'fixed' if success else 'failed'}")
        lines.append("")

    # Native build details
    build_outcome = state.stage_outcomes.get("native_build", {})
    if build_outcome:
        build_ev = build_outcome.get("evidence", {})
        lines.append("## Native Build")
        if state.native_binary_path:
            lines.append(f"- Binary: `{state.native_binary_path}`")
        if state.native_artifact_hash:
            lines.append(f"- SHA-256: `{state.native_artifact_hash}`")
        if build_ev.get("errors"):
            lines.append(f"- Errors: {build_ev['errors']}")
        lines.append("")

    # Verification
    if state.verification_results:
        lines.append("## Differential Verification")
        lines.append(f"- Total cases: {len(state.verification_results)}")
        passed = sum(1 for r in state.verification_results if r.get("passed"))
        lines.append(f"- Passed: {passed}")
        lines.append(f"- Failed: {len(state.verification_results) - passed}")
        lines.append("")
        for vr in state.verification_results:
            icon = "✅" if vr.get("passed") else "❌"
            lines.append(f"- {icon} {vr.get('case_name', '?')}")
        lines.append("")

    # Warnings and errors
    if state.warnings:
        lines.append("## Warnings")
        for w in state.warnings:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    if state.errors:
        lines.append("## Errors")
        for e in state.errors:
            lines.append(f"- ❌ {e}")
        lines.append("")

    # Definition of verified
    lines.append("## Definition of 'verified'")
    lines.append("")
    lines.append("A run is `verified` only when ALL of:")
    lines.append("1. Rust workspace builds in release mode")
    lines.append("2. `cargo fmt --check` passes")
    lines.append("3. `cargo clippy --all-targets --all-features -- -D warnings` passes")
    lines.append("4. `cargo test --all-targets --all-features` passes")
    lines.append("5. Every configured oracle case passes differential verification")
    lines.append("6. Evidence points to actual commands and artifacts")
    lines.append("")

    # Limitations
    lines.append("## Limitations")
    lines.append("- Dynamic Python behavior (reflection, monkeypatching) cannot be fully captured")
    lines.append("- Nondeterministic outputs cannot be verified")
    lines.append("- Network-dependent behavior may differ")
    lines.append("- Database, GUI, and distributed system ports are out of scope")
    lines.append("- Native C/Fortran dependencies require manual handling")
    lines.append("")

    content = "\n".join(lines)
    path = run_dir / "report.md"
    path.write_text(content, encoding="utf-8")
    return path
