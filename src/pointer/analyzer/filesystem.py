"""Filesystem-safe traversal utilities.

Core safety guarantee: never follow symlinks outside the repository root.
All directory walks check for symlink escape.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

# Default exclusion patterns
DEFAULT_EXCLUDES = [
    ".git",
    "__pycache__",
    "*.egg-info",
    "*.dist-info",
    ".tox",
    ".nox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".env",
    "build",
    "dist",
    ".eggs",
    ".eggs",
    "site-packages",
    ".sass-cache",
    ".idea",
    ".vscode",
]

# Compiled extension suffixes for native compiled files (platform-aware)
NATIVE_SUFFIXES = {
    ".so",  # Linux/macOS shared object
    ".pyd",  # Windows Python extension
    ".dylib",  # macOS dynamic library
}

# Python file extensions
PY_SUFFIXES = {".py", ".pyi"}

# Known lockfile names
LOCKFILE_MAP = {
    "uv.lock": "uv",
    "poetry.lock": "poetry",
    "pdm.lock": "pdm",
    "requirements.txt": "pip",
    "requirements-dev.txt": "pip",
    "requirements-test.txt": "pip",
    "requirements_prod.txt": "pip",
    "requirements-prod.txt": "pip",
    "Pipfile.lock": "pipenv",
    "pipfile.lock": "pipenv",
}


def is_excluded(name: str, path: str, excludes: list[str]) -> bool:
    """Check if a file/dir name matches any exclusion pattern."""
    for pattern in excludes:
        if fnmatch.fnmatch(name, pattern):
            return True
        # Also check full relative path
        if fnmatch.fnmatch(path, pattern):
            return True
    return False


def safe_resolve(path: Path, root: Path) -> Path | None:
    """Resolve a path and check it doesn't escape the root via symlinks.

    Returns the resolved path if safe, None if it escapes.
    """
    try:
        resolved = path.resolve(strict=False)
        root_resolved = root.resolve(strict=False)
    except (OSError, RuntimeError):
        return None

    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None

    return resolved


def safe_walk(root: Path, excludes: list[str] | None = None) -> list[tuple[Path, str]]:
    """Safely walk a directory tree, never following symlinks outside root.

    Returns list of (filepath, relative_path_string) tuples.
    """
    if excludes is None:
        excludes = DEFAULT_EXCLUDES

    results: list[tuple[Path, str]] = []
    root_resolved = root.resolve()

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current_dir = Path(dirpath)

        # Filter excluded directories (modify dirnames in-place to prevent descent)
        rel_dir = current_dir.relative_to(root) if current_dir != root else Path(".")
        rel_dir_str = str(rel_dir) if str(rel_dir) != "." else ""

        dirnames[:] = [d for d in dirnames if not is_excluded(d, f"{rel_dir_str}/{d}" if rel_dir_str else d, excludes)]

        # Check each directory isn't a symlink pointing outside root
        safe_dirs = []
        for d in dirnames:
            full = current_dir / d
            if full.is_symlink():
                resolved = safe_resolve(full, root_resolved)
                if resolved is None:
                    continue  # symlink escapes root — skip
            safe_dirs.append(d)
        dirnames[:] = safe_dirs

        for fname in filenames:
            rel_path = f"{rel_dir_str}/{fname}" if rel_dir_str else fname
            if is_excluded(fname, rel_path, excludes):
                continue

            full = current_dir / fname

            # Check symlinks for files
            if full.is_symlink():
                resolved = safe_resolve(full, root_resolved)
                if resolved is None:
                    continue  # symlink escapes root

            results.append((full, rel_path))

    return results


def read_text_safely(path: Path, max_size: int = 5 * 1024 * 1024) -> str | None:
    """Read a text file safely, with size limit and encoding fallback.

    Returns None if the file cannot be read as text.
    """
    try:
        size = path.stat().st_size
        if size > max_size:
            return None
    except OSError:
        return None

    for encoding in ("utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, OSError):
            continue
    return None
