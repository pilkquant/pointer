"""Pointer CLI — command-line interface.

Commands:
  pointer analyze PATH [--target compare|rust|cpp] [--output DIR] [--exclude GLOB ...]
  pointer port PATH --target rust --agent codex [--yes] [--allow-source-execution]
  pointer status [RUN_ID]
  pointer continue RUN_ID
  pointer verify RUN_ID
  pointer doctor
  pointer --version
  pointer --help

Exit codes: 0 success, 1 internal failure, 2 invalid arguments/path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pointer import __version__
from pointer.doctor import format_doctor, run_doctor
from pointer.models import Target
from pointer.pipeline import analyze
from pointer.porting.runner import PortRunner, resume_run
from pointer.porting.state import (
    default_state_root,
    list_runs,
    load_state,
    run_directory,
)
from pointer.report.json_out import write_json
from pointer.report.markdown import write_markdown


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="pointer",
        description=(
            "Pointer — Point it at Python. Get an evidence-backed path to native.\n\n"
            "Static portability analysis + Codex-backed Python→Rust porting.\n"
            "Pointer never imports or executes code from the target repository\n"
            "unless you explicitly authorize source execution."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  pointer analyze ./my-project\n"
            "  pointer analyze ./my-project --target rust\n"
            "  pointer port ./my-project --target rust --agent codex\n"
            "  pointer port ./my-project --target rust --agent codex --yes --allow-source-execution\n"
            "  pointer status\n"
            "  pointer continue <run-id>\n"
            "  pointer doctor\n"
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"pointer {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # analyze
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze a Python repository for portability",
        description=(
            "Analyze a Python repository and produce portability reports.\n\n"
            "Outputs report.md and report.json in the output directory.\n"
            "Default output: ./pointer-report/\n\n"
            "Pointer performs static analysis only — it never imports or\n"
            "executes code from the target repository."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    analyze_parser.add_argument(
        "path",
        type=str,
        help="Path to the Python repository to analyze",
    )

    analyze_parser.add_argument(
        "--target",
        type=str,
        choices=[t.value for t in Target],
        default=Target.COMPARE.value,
        help="Target language for analysis (default: compare)",
    )

    analyze_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="pointer-report",
        help="Output directory for reports (default: pointer-report)",
    )

    analyze_parser.add_argument(
        "--exclude",
        type=str,
        action="append",
        default=[],
        help="Additional glob patterns to exclude (in addition to defaults)",
    )

    # port
    port_parser = subparsers.add_parser(
        "port",
        help="Port a Python repository to Rust using an AI agent",
        description=(
            "Port a Python repository to Rust using an AI agent backend.\n\n"
            "Runs the full pipeline: analysis → oracle capture → plan → generation →\n"
            "build/test → differential verification → bounded repair → evidence report.\n\n"
            "By default, source execution is NOT allowed. Use --allow-source-execution\n"
            "to capture Python oracle outputs for verification.\n\n"
            "This command creates an isolated output workspace and contacts the\n"
            "selected agent. It does NOT modify the source repository."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    port_parser.add_argument(
        "path",
        type=str,
        help="Path to the Python repository to port",
    )

    port_parser.add_argument(
        "--target",
        type=str,
        choices=["rust"],
        default="rust",
        help="Target language (default: rust)",
    )

    port_parser.add_argument(
        "--agent",
        type=str,
        choices=["codex", "fake"],
        default="codex",
        help="Agent backend to use (default: codex)",
    )

    port_parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Auto-confirm non-interactive (does NOT grant source execution consent)",
    )

    port_parser.add_argument(
        "--allow-source-execution",
        action="store_true",
        default=False,
        help="Allow executing the Python source as an oracle (security boundary)",
    )

    port_parser.add_argument(
        "--max-repairs",
        type=int,
        default=3,
        help="Maximum repair attempts (default: 3)",
    )

    port_parser.add_argument(
        "--state-root",
        type=str,
        default=None,
        help="Override state root directory (default: .pointer/runs)",
    )

    # status
    status_parser = subparsers.add_parser(
        "status",
        help="Show status of porting runs",
        description="List all porting runs or show details of a specific run.",
    )

    status_parser.add_argument(
        "run_id",
        type=str,
        nargs="?",
        default=None,
        help="Run ID to show details for (omit to list all runs)",
    )

    status_parser.add_argument(
        "--state-root",
        type=str,
        default=None,
        help="Override state root directory",
    )

    status_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output as JSON",
    )

    # continue
    continue_parser = subparsers.add_parser(
        "continue",
        help="Resume an interrupted porting run",
        description="Resume a porting run from where it left off.",
    )

    continue_parser.add_argument(
        "run_id",
        type=str,
        help="Run ID to resume",
    )

    continue_parser.add_argument(
        "--max-repairs",
        type=int,
        default=None,
        help="Override max repair attempts",
    )

    continue_parser.add_argument(
        "--state-root",
        type=str,
        default=None,
        help="Override state root directory",
    )

    # verify
    verify_parser = subparsers.add_parser(
        "verify",
        help="Re-run verification on a completed porting run",
        description="Re-run differential verification on a completed run.",
    )

    verify_parser.add_argument(
        "run_id",
        type=str,
        help="Run ID to verify",
    )

    verify_parser.add_argument(
        "--state-root",
        type=str,
        default=None,
        help="Override state root directory",
    )

    # doctor
    subparsers.add_parser(
        "doctor",
        help="Check Pointer environment and capabilities",
        description="Report Pointer version, platform info, and optional tool availability.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point. Returns exit code."""
    # Ensure UTF-8 output on all platforms (Windows defaults to cp1252)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    parser = build_parser()

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "doctor":
        result = run_doctor()
        print(format_doctor(result))
        return 0

    if args.command == "analyze":
        return _cmd_analyze(args)

    if args.command == "port":
        return _cmd_port(args)

    if args.command == "status":
        return _cmd_status(args)

    if args.command == "continue":
        return _cmd_continue(args)

    if args.command == "verify":
        return _cmd_verify(args)

    # Should not reach here
    parser.print_help()
    return 2


def _cmd_analyze(args: argparse.Namespace) -> int:
    """Execute the analyze command."""
    target_path = Path(args.path)
    if not target_path.exists():
        print(f"Error: path does not exist: {target_path}", file=sys.stderr)
        return 2

    if not target_path.is_dir():
        print(f"Error: path is not a directory: {target_path}", file=sys.stderr)
        return 2

    target_path = target_path.resolve()

    output_dir = Path(args.output)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Error: cannot create output directory {output_dir}: {e}", file=sys.stderr)
        return 2

    try:
        target = Target(args.target)
    except ValueError:
        print(f"Error: invalid target '{args.target}'", file=sys.stderr)
        return 2

    print(f"Pointer {__version__} — analyzing {target_path}", file=sys.stderr)
    print(f"Target: {target.value}", file=sys.stderr)

    try:
        report = analyze(target_path, target)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: analysis failed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return 1

    try:
        md_path = write_markdown(report, output_dir)
        json_path = write_json(report, output_dir)
    except OSError as e:
        print(f"Error: failed to write reports: {e}", file=sys.stderr)
        return 1

    print("\n✓ Analysis complete.", file=sys.stderr)
    print(f"  Markdown: {md_path}", file=sys.stderr)
    print(f"  JSON:     {json_path}", file=sys.stderr)
    print(f"\n{report.summary}", file=sys.stderr)

    return 0


def _cmd_port(args: argparse.Namespace) -> int:
    """Execute the port command."""
    source_path = Path(args.path)
    if not source_path.exists():
        print(f"Error: path does not exist: {source_path}", file=sys.stderr)
        return 2
    if not source_path.is_dir():
        print(f"Error: path is not a directory: {source_path}", file=sys.stderr)
        return 2

    source_path = source_path.resolve()

    state_root = Path(args.state_root) if args.state_root else default_state_root()
    state_root.mkdir(parents=True, exist_ok=True)
    output_parent = state_root.parent / "output"

    print(f"Pointer {__version__} — porting {source_path}", file=sys.stderr)
    print(f"Target: {args.target}", file=sys.stderr)
    print(f"Agent:  {args.agent}", file=sys.stderr)

    if args.allow_source_execution:
        print("Source execution: ENABLED (oracle capture will run Python source)", file=sys.stderr)
    else:
        print("Source execution: disabled (use --allow-source-execution for verification)", file=sys.stderr)

    runner = PortRunner(
        source_path=str(source_path),
        target_lang=args.target,
        agent_name=args.agent,
        state_root=state_root,
        output_parent=output_parent,
        allow_source_execution=args.allow_source_execution,
        auto_yes=args.yes,
        max_repairs=args.max_repairs,
    )

    try:
        result = runner.run()
    except KeyboardInterrupt:
        print("\nInterrupted. State saved. Use 'pointer continue <run-id>' to resume.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: porting failed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return 1

    # Print result
    state = result.state
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(f"Run ID: {state.run_id}", file=sys.stderr)
    print(f"Verdict: {result.verdict}", file=sys.stderr)
    print(f"Message: {result.message}", file=sys.stderr)
    print(f"Run dir: {state.run_dir}", file=sys.stderr)

    if state.native_artifact_hash:
        print(f"Binary SHA-256: {state.native_artifact_hash}", file=sys.stderr)
    if state.repair_count > 0:
        print(f"Repairs: {state.repair_count}/{state.max_repairs}", file=sys.stderr)

    # Show verification summary
    if state.verification_results:
        passed = sum(1 for r in state.verification_results if r.get("passed"))
        total = len(state.verification_results)
        print(f"Oracle cases: {passed}/{total} passed", file=sys.stderr)

    report_path = Path(state.run_dir) / "report.md"
    evidence_path = Path(state.run_dir) / "evidence.json"
    print(f"\nReport:  {report_path}", file=sys.stderr)
    print(f"Evidence: {evidence_path}", file=sys.stderr)

    return 0 if result.success else 1


def _cmd_status(args: argparse.Namespace) -> int:
    """Show status of porting runs."""
    state_root = Path(args.state_root) if args.state_root else default_state_root()

    if args.run_id:
        # Show specific run
        run_dir = run_directory(state_root, args.run_id)
        state = load_state(run_dir)
        if state is None:
            print(f"Error: run not found: {args.run_id}", file=sys.stderr)
            return 2

        if args.json:
            print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        else:
            _print_run_detail(state)
        return 0
    else:
        # List all runs
        runs = list_runs(state_root)
        if not runs:
            print("No porting runs found.", file=sys.stderr)
            return 0

        if args.json:
            print(json.dumps(runs, indent=2, ensure_ascii=False))
        else:
            print(f"{'Run ID':<28} {'Stage':<22} {'Verdict':<22} {'Source'}")
            print("-" * 100)
            for run in runs:
                src = run.get("source", "")
                # Shorten source path
                if len(src) > 30:
                    src = "..." + src[-27:]
                print(f"{run['run_id']:<28} {run.get('stage', '?'):<22} {str(run.get('verdict', '')):<22} {src}")
        return 0


def _cmd_continue(args: argparse.Namespace) -> int:
    """Resume an interrupted run."""
    state_root = Path(args.state_root) if args.state_root else default_state_root()

    print(f"Resuming run: {args.run_id}", file=sys.stderr)

    try:
        result = resume_run(args.run_id, state_root)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted. State saved.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: resume failed: {e}", file=sys.stderr)
        return 1

    state = result.state
    print(f"\nRun ID: {state.run_id}", file=sys.stderr)
    print(f"Verdict: {result.verdict}", file=sys.stderr)
    print(f"Stage: {state.stage}", file=sys.stderr)

    return 0 if result.success else 1


def _cmd_verify(args: argparse.Namespace) -> int:
    """Re-run verification on a completed run."""
    state_root = Path(args.state_root) if args.state_root else default_state_root()
    run_dir = run_directory(state_root, args.run_id)
    state = load_state(run_dir)

    if state is None:
        print(f"Error: run not found: {args.run_id}", file=sys.stderr)
        return 2

    print(f"Run: {state.run_id}", file=sys.stderr)
    print(f"Current verdict: {state.verdict}", file=sys.stderr)
    print(f"Binary: {state.native_binary_path}", file=sys.stderr)

    if state.verification_results:
        passed = sum(1 for r in state.verification_results if r.get("passed"))
        total = len(state.verification_results)
        print(f"Cases: {passed}/{total} passed", file=sys.stderr)
    else:
        print("No verification results recorded.", file=sys.stderr)

    return 0


def _print_run_detail(state) -> None:
    """Print detailed status for a single run."""
    print(f"Run ID:     {state.run_id}")
    print(f"Stage:      {state.stage}")
    print(f"Verdict:    {state.verdict}")
    print(f"Created:    {state.created_at}")
    print(f"Updated:    {state.updated_at}")
    print(f"Source:     {state.source_path}")
    print(f"Output:     {state.output_dir}")
    print(f"Run dir:    {state.run_dir}")
    print(f"Agent:      {state.agent_backend} ({state.agent_backend_version})")
    print(f"Target:     {state.target_lang}")
    print(f"Consent:    {'yes' if state.consent_given else 'no'}")
    print(f"Repairs:    {state.repair_count}/{state.max_repairs}")

    if state.native_binary_path:
        print(f"Binary:     {state.native_binary_path}")
    if state.native_artifact_hash:
        print(f"SHA-256:    {state.native_artifact_hash}")

    if state.stage_outcomes:
        print("\nStages:")
        for stage_name, outcome in state.stage_outcomes.items():
            status = outcome.get("status", "?")
            icon = "✓" if status == "completed" else "✗" if status == "failed" else "→"
            print(f"  {icon} {stage_name}: {status}")

    if state.warnings:
        print(f"\nWarnings ({len(state.warnings)}):")
        for w in state.warnings[-5:]:
            print(f"  ⚠ {w}")

    if state.errors:
        print(f"\nErrors ({len(state.errors)}):")
        for e in state.errors[-5:]:
            print(f"  ✗ {e}")


if __name__ == "__main__":
    sys.exit(main())
