"""Code metrics: LOC, file counts, module inventory.

Counts physical and logical lines of code without executing anything.
"""

from __future__ import annotations

from pathlib import Path

from pointer.analyzer.filesystem import PY_SUFFIXES, read_text_safely, safe_walk
from pointer.models import CodeMetrics


def measure(root: Path) -> CodeMetrics:
    """Measure code metrics for the repository."""
    metrics = CodeMetrics()
    all_files = safe_walk(root)

    files_by_type: dict[str, int] = {}
    file_sizes: list[dict] = []

    for fpath, _rel in all_files:
        ext = fpath.suffix.lower() if fpath.suffix else "(no ext)"
        files_by_type[ext] = files_by_type.get(ext, 0) + 1

        if fpath.suffix in PY_SUFFIXES and fpath.suffix != ".pyi":
            metrics.total_py_files += 1
            source = read_text_safely(fpath)
            if source is not None:
                lines = source.splitlines()
                metrics.total_py_lines += len(lines)

                # Count logical lines (non-blank, non-comment)
                logical = 0
                for line in lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        logical += 1
                metrics.total_py_logical_lines += logical

                file_sizes.append(
                    {
                        "path": str(fpath),
                        "lines": len(lines),
                        "logical_lines": logical,
                    }
                )

    metrics.files_by_type = dict(sorted(files_by_type.items(), key=lambda x: -x[1]))
    metrics.largest_files = sorted(file_sizes, key=lambda x: -x["lines"])[:20]

    # Count modules (directories with __init__.py)
    init_count = 0
    for fpath, _rel in all_files:
        if fpath.name == "__init__.py":
            init_count += 1
    metrics.module_count = init_count

    return metrics
