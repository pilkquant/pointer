"""Doctor command — reports Pointer/platform version and capabilities.

Reports availability of tools needed for static analysis (v0.1) and
porting (v0.2: codex, cargo, rustc, clippy, rustfmt).
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass, field

from pointer import __version__


@dataclass
class DoctorResult:
    """Result of the doctor check."""

    pointer_version: str = __version__
    python_version: str = ""
    platform: str = ""
    optional_tools: dict[str, bool] = field(default_factory=dict)
    porting_tools: dict[str, bool] = field(default_factory=dict)
    all_good: bool = True


def run_doctor() -> DoctorResult:
    """Run environment diagnostics."""
    result = DoctorResult(
        python_version=sys.version,
        platform=platform.platform(),
    )

    # Check optional tools (not required for 0.1 static analysis)
    optional_tools = [
        "git",
        "rustc",
        "cargo",
        "cc",  # C compiler
        "c++",  # C++ compiler
        "cmake",
        "make",
        "ninja",
    ]

    for tool in optional_tools:
        path = shutil.which(tool)
        result.optional_tools[tool] = path is not None

    # Check porting tools (v0.2)
    porting_tools = ["cargo", "rustc", "cargo-clippy", "cargo-fmt", "codex"]
    for tool in porting_tools:
        if tool == "codex":
            # Check POINTER_CODEX_BIN first
            override = os.environ.get("POINTER_CODEX_BIN")
            if override:
                result.porting_tools[tool] = os.path.exists(override)
                continue
        result.porting_tools[tool] = shutil.which(tool) is not None

    # Doctor always succeeds — external tools are optional
    result.all_good = True

    return result


def format_doctor(result: DoctorResult) -> str:
    """Format doctor results as readable text."""
    lines: list[str] = []
    lines.append(f"Pointer {result.pointer_version}")
    lines.append(f"Python: {result.python_version.split('(')[0].strip()}")
    lines.append(f"Platform: {result.platform}")
    lines.append("")
    lines.append("Optional tools (not required for static analysis):")
    for tool, available in sorted(result.optional_tools.items()):
        status = "✓ available" if available else "✗ not found"
        lines.append(f"  {tool}: {status}")
    lines.append("")
    lines.append("Porting tools (for `pointer port`):")
    for tool, available in sorted(result.porting_tools.items()):
        status = "✓ available" if available else "✗ not found"
        lines.append(f"  {tool}: {status}")
    lines.append("")
    lines.append("All core requirements met. Pointer is ready.")
    if not result.porting_tools.get("codex"):
        lines.append("Note: codex not found. Install Codex CLI or set POINTER_CODEX_BIN for `pointer port`.")
    if not result.porting_tools.get("cargo"):
        lines.append("Note: cargo not found. Install Rust toolchain for `pointer port`.")
    return "\n".join(lines)
