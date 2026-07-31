"""Pointer CLI — command-line interface.

Commands:
  pointer analyze PATH [--target compare|rust|cpp] [--output DIR] [--exclude GLOB ...]
  pointer doctor
  pointer --version
  pointer --help

Exit codes: 0 success, 1 internal failure, 2 invalid arguments/path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pointer import __version__
from pointer.doctor import format_doctor, run_doctor
from pointer.models import Target
from pointer.pipeline import analyze
from pointer.report.json_out import write_json
from pointer.report.markdown import write_markdown


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="pointer",
        description=(
            "Pointer — Point it at Python. Get an evidence-backed path to native.\n\n"
            "Static portability analysis for Python -> Rust/C++ migration.\n"
            "Pointer never imports or executes code from the target repository."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  pointer analyze ./my-project\n"
            "  pointer analyze ./my-project --target rust\n"
            "  pointer analyze ./my-project --output ./reports --exclude '*.pb.*'\n"
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

    # Should not reach here
    parser.print_help()
    return 2


def _cmd_analyze(args: argparse.Namespace) -> int:
    """Execute the analyze command."""
    # Validate path
    target_path = Path(args.path)
    if not target_path.exists():
        print(f"Error: path does not exist: {target_path}", file=sys.stderr)
        return 2

    if not target_path.is_dir():
        print(f"Error: path is not a directory: {target_path}", file=sys.stderr)
        return 2

    # Resolve to absolute path
    target_path = target_path.resolve()

    # Validate output directory parent is writable
    output_dir = Path(args.output)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"Error: cannot create output directory {output_dir}: {e}", file=sys.stderr)
        return 2

    # Parse target
    try:
        target = Target(args.target)
    except ValueError:
        print(f"Error: invalid target '{args.target}'", file=sys.stderr)
        return 2

    # Print start message
    print(f"Pointer {__version__} — analyzing {target_path}", file=sys.stderr)
    print(f"Target: {target.value}", file=sys.stderr)

    # Run analysis
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

    # Write reports
    try:
        md_path = write_markdown(report, output_dir)
        json_path = write_json(report, output_dir)
    except OSError as e:
        print(f"Error: failed to write reports: {e}", file=sys.stderr)
        return 1

    # Print summary to stderr
    print("\n✓ Analysis complete.", file=sys.stderr)
    print(f"  Markdown: {md_path}", file=sys.stderr)
    print(f"  JSON:     {json_path}", file=sys.stderr)
    print(f"\n{report.summary}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
