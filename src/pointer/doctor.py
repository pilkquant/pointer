"""Doctor command — reports Pointer/platform version and capabilities.

Does NOT require external tools. Reports their absence gracefully.
"""

from __future__ import annotations

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
    all_good: bool = True


def run_doctor() -> DoctorResult:
    """Run environment diagnostics."""
    result = DoctorResult(
        python_version=sys.version,
        platform=platform.platform(),
    )

    # Check optional tools (not required for 0.1, but useful if present)
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
    lines.append("All core requirements met. Pointer is ready for static analysis.")
    return "\n".join(lines)
