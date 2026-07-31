"""Prompt construction — builds structured, bounded context for the agent.

Feeds the agent staged context: analysis JSON, source tree, oracle transcripts,
target Rust constraints, migration plan, and acceptance checks.

Avoids one giant opaque prompt. Each section is versioned and inspectable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import PortConfig
from .oracle import OracleCaptureResult
from .security import redact_secrets, truncate_output

PROMPT_VERSION = "1"

# Size limits to keep prompts bounded
MAX_SOURCE_FILES = 20
MAX_FILE_CHARS = 10000
MAX_TOTAL_SOURCE_CHARS = 50000


def _format_source_tree(source_root: Path, max_files: int = MAX_SOURCE_FILES) -> str:
    """Format a bounded view of the source tree for the prompt."""
    lines: list[str] = []
    total_chars = 0
    file_count = 0

    for py_file in sorted(source_root.rglob("*.py")):
        # Skip hidden dirs, __pycache__, tests/fixtures
        rel = py_file.relative_to(source_root)
        rel_str = str(rel)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if "__pycache__" in rel_str:
            continue
        if "test" in rel_str.lower() and "fixture" not in rel_str.lower():
            continue

        if file_count >= max_files:
            lines.append(f"... [truncated: {max_files} files limit reached]")
            break

        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        content = truncate_output(content, MAX_FILE_CHARS)
        if total_chars + len(content) > MAX_TOTAL_SOURCE_CHARS:
            remaining = MAX_TOTAL_SOURCE_CHARS - total_chars
            if remaining > 200:
                content = truncate_output(content, remaining)
            else:
                lines.append(f"... [source size limit reached at {rel_str}]")
                break

        total_chars += len(content)
        file_count += 1
        lines.append(f"\n{'=' * 60}")
        lines.append(f"FILE: {rel_str}")
        lines.append(f"{'=' * 60}")
        lines.append(content)

    return "\n".join(lines) if lines else "(no Python source files found)"


def _format_oracle_transcript(oracle_result: OracleCaptureResult) -> str:
    """Format captured oracle outputs for the prompt."""
    if not oracle_result.cases:
        return "(no oracle cases captured)"

    lines: list[str] = []
    for case in oracle_result.cases:
        lines.append(f"\n--- Case: {case.name} ---")
        lines.append(f"Command: {' '.join(case.command)}")
        if case.timed_out:
            lines.append(f"Result: TIMED OUT ({case.error})")
            continue
        lines.append(f"Exit code: {case.exit_code}")
        if case.stdout_normalized:
            lines.append(f"stdout:\n{truncate_output(case.stdout_normalized, 2000)}")
        if case.stderr_normalized:
            lines.append(f"stderr:\n{truncate_output(case.stderr_normalized, 500)}")

    return "\n".join(lines)


def _format_analysis_json(analysis_data: dict[str, Any]) -> str:
    """Format the v0.1 analysis JSON for the prompt."""
    # Compact representation, redacted
    text = json.dumps(analysis_data, indent=2, ensure_ascii=False, default=str)
    text = redact_secrets(text)
    return truncate_output(text, 10000)


def build_generation_prompt(
    source_root: Path,
    port_config: PortConfig,
    oracle_result: OracleCaptureResult | None,
    analysis_json: dict[str, Any] | None,
    output_dir: Path,
) -> str:
    """Build the full generation prompt for the agent.

    This is a structured, staged prompt — not one opaque block.
    """
    sections: list[str] = []

    # --- Section 1: Mission ---
    sections.append(f"""# Pointer Port Generation Request (prompt v{PROMPT_VERSION})

You are generating a Rust port of a Python project. Your output will be built,
tested, and differentially verified against the Python oracle.

## Rules
- Create a conventional Rust workspace in the output directory: {output_dir}
- Write a Cargo.toml with package name "port-target" and a binary target
- Write idiomatic, clean Rust code (will be checked with clippy -D warnings)
- Write tests (will be run with cargo test)
- Preserve the EXACT observable behavior of the Python source for all oracle cases
- The Rust binary must accept the same CLI arguments and stdin as the Python source
- Do NOT add unnecessary dependencies — prefer std only
- Do NOT print debug output to stdout — only the expected program output""")

    # --- Section 2: Source code ---
    sections.append(f"""
# Source Code

{_format_source_tree(source_root)}""")

    # --- Section 3: Analysis summary ---
    if analysis_json:
        sections.append(f"""
# Static Analysis Summary

{_format_analysis_json(analysis_json)}""")

    # --- Section 4: Oracle specification ---
    if oracle_result and oracle_result.cases:
        sections.append(f"""
# Oracle Specification (reference behavior)

The following are captured outputs from running the Python source.
Your Rust port MUST produce identical stdout, stderr, and exit codes for each case
(after normalization: trailing whitespace stripped, newlines normalized).

{_format_oracle_transcript(oracle_result)}""")

    # --- Section 5: Port config ---
    if port_config.oracle_cases:
        cases_summary = "\n".join(
            f"  - {c.name}: {' '.join(c.command)}" + (f" (stdin: {c.stdin!r})" if c.stdin else "")
            for c in port_config.oracle_cases
        )
        sections.append(f"""
# Oracle Cases to Support

{cases_summary}""")

    # --- Section 6: Acceptance criteria ---
    sections.append("""
# Acceptance Criteria

Your generated Rust workspace must pass ALL of:
1. `cargo fmt --check` — formatted correctly
2. `cargo clippy --all-targets --all-features -- -D warnings` — no warnings
3. `cargo test --all-targets --all-features` — all tests pass
4. `cargo build --release` — builds in release mode
5. Every oracle case produces identical output to the Python source

Generate the complete Rust workspace now. Write Cargo.toml and src/main.rs.
""")

    return "\n".join(sections)


def build_repair_prompt(
    build_result: dict[str, Any],
    verification_result: dict[str, Any] | None,
    repair_attempt: int,
    max_repairs: int,
) -> str:
    """Build a repair prompt from structured diagnostics.

    Contains only relevant diagnostics and expected behavior.
    """
    sections: list[str] = []

    sections.append(f"""# Pointer Repair Request (attempt {repair_attempt}/{max_repairs})

The generated Rust workspace has issues that need fixing. Below are the exact
diagnostics. Fix them while preserving correct behavior for all oracle cases.
""")

    # Build failures
    errors = build_result.get("errors", [])
    if errors:
        sections.append("## Build Errors\n")
        for err in errors:
            sections.append(f"- {err}")

    # Fmt output
    fmt = build_result.get("fmt")
    if fmt and not fmt.get("success"):
        sections.append(f"""
## cargo fmt --check output
```
{truncate_output(fmt.get("stdout", "") + fmt.get("stderr", ""), 3000)}
```""")

    # Clippy output
    clippy = build_result.get("clippy")
    if clippy and not clippy.get("success"):
        sections.append(f"""
## cargo clippy output
```
{truncate_output(clippy.get("stdout", "") + clippy.get("stderr", ""), 5000)}
```""")

    # Test output
    test = build_result.get("test")
    if test and not test.get("success"):
        sections.append(f"""
## cargo test output
```
{truncate_output(test.get("stdout", "") + test.get("stderr", ""), 5000)}
```""")

    # Build output
    build = build_result.get("build")
    if build and not build.get("success"):
        sections.append(f"""
## cargo build --release output
```
{truncate_output(build.get("stdout", "") + build.get("stderr", ""), 5000)}
```""")

    # Verification mismatches
    if verification_result and verification_result.get("mismatches"):
        sections.append("\n## Behavioral Mismatches\n")
        for mismatch in verification_result["mismatches"]:
            sections.append(
                f"- Case '{mismatch['case_name']}' field '{mismatch['field']}':\n"
                f"  Expected: {mismatch['expected']}\n"
                f"  Actual: {mismatch['actual']}"
            )

    sections.append("""
Fix the issues. Rewrite the affected files. Ensure all acceptance criteria pass.
""")

    return "\n".join(sections)


def write_prompt_to_file(
    prompt: str,
    run_dir: Path,
    name: str,
) -> Path:
    """Write a prompt to a file in the run directory for inspection."""
    prompt_path = run_dir / f"prompt-{name}.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path
