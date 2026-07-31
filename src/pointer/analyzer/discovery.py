"""Packaging, build system, lockfile, and entry point discovery.

Discovers the project structure by looking for well-known files.
Never imports or executes any target code.
"""

from __future__ import annotations

import re
import tomllib  # type: ignore[no-redef]
from pathlib import Path

from pointer.analyzer.filesystem import LOCKFILE_MAP, PY_SUFFIXES, safe_walk
from pointer.models import (
    BuildSystem,
    EntryPoint,
    Evidence,
    FileEntry,
    Lockfile,
    ProjectStructure,
    SourceRoot,
)

# Build backend → build system name mapping
BACKEND_MAP = {
    "setuptools": "setuptools",
    "hatchling": "hatch",
    "hatch": "hatch",
    "flit_core": "flit",
    "flit": "flit",
    "poetry.core.masonry.api": "poetry",
    "pdm.backend": "pdm",
    "maturin": "maturin",
    "mesonpy": "meson-python",
    "scikit_build_core": "scikit-build-core",
    "setuptools_rust": "setuptools-rust",
}

# Known source root patterns
SRC_PATTERNS = ["src", "lib", "python"]

# setup.cfg section that may declare packages
SETUP_CFG_PACKAGE_RE = re.compile(r"^\s*find\s*:", re.MULTILINE)


def discover(root: Path) -> ProjectStructure:
    """Discover project structure from the repository root."""
    structure = ProjectStructure(root=str(root))
    all_files = safe_walk(root)

    # Index files by basename for quick lookup
    files_by_basename: dict[str, list[tuple[Path, str]]] = {}
    for fpath, rel in all_files:
        basename = fpath.name
        files_by_basename.setdefault(basename, []).append((fpath, rel))

    # --- pyproject.toml ---
    pyproject_files = files_by_basename.get("pyproject.toml", [])
    if pyproject_files:
        pyproject_path, rel = pyproject_files[0]
        structure.files.append(FileEntry(path=rel, kind="pyproject"))
        _parse_pyproject(pyproject_path, structure)

    # --- setup.cfg ---
    setup_cfg_files = files_by_basename.get("setup.cfg", [])
    if setup_cfg_files:
        path, rel = setup_cfg_files[0]
        structure.files.append(FileEntry(path=rel, kind="config"))
        _parse_setup_cfg(path, structure)

    # --- setup.py ---
    setup_py_files = files_by_basename.get("setup.py", [])
    if setup_py_files:
        path, rel = setup_py_files[0]
        structure.files.append(FileEntry(path=rel, kind="config"))
        if not any(b.name == "setuptools" for b in structure.build_systems):
            structure.build_systems.append(
                BuildSystem(
                    name="setuptools",
                    backend="setup.py",
                    evidence=Evidence.OBSERVED,
                    source_file=rel,
                )
            )

    # --- Lockfiles ---
    for fpath, rel in all_files:
        if fpath.name in LOCKFILE_MAP:
            structure.files.append(FileEntry(path=rel, kind="lockfile"))
            structure.lockfiles.append(Lockfile(path=rel, kind=LOCKFILE_MAP[fpath.name]))
        elif fpath.name.startswith("requirements") and fpath.suffix == ".txt":
            structure.files.append(FileEntry(path=rel, kind="lockfile"))
            structure.lockfiles.append(Lockfile(path=rel, kind="pip"))

    # --- MANIFEST.in ---
    if files_by_basename.get("MANIFEST.in"):
        path, rel = files_by_basename["MANIFEST.in"][0]
        structure.files.append(FileEntry(path=rel, kind="config"))

    # --- Source roots ---
    _discover_source_roots(root, all_files, structure)

    # --- All Python files ---
    for fpath, rel in all_files:
        if fpath.suffix in PY_SUFFIXES:
            structure.files.append(FileEntry(path=rel, kind="python"))

    return structure


def _parse_pyproject(path: Path, structure: ProjectStructure) -> None:
    """Parse pyproject.toml for project metadata and build system."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        structure.errors.append(f"Failed to parse pyproject.toml: {e}")
        return

    structure.pyproject_data = data

    # Build system
    build_sys = data.get("build-system", {})
    requires = build_sys.get("requires", [])
    backend = build_sys.get("build-backend", "")

    if backend:
        for key, name in BACKEND_MAP.items():
            if key in backend:
                structure.build_systems.append(
                    BuildSystem(
                        name=name,
                        backend=backend,
                        evidence=Evidence.OBSERVED,
                        source_file="pyproject.toml",
                    )
                )
                break
        else:
            # Unknown backend — record it
            structure.build_systems.append(
                BuildSystem(
                    name=backend,
                    backend=backend,
                    evidence=Evidence.OBSERVED,
                    source_file="pyproject.toml",
                )
            )
    elif requires:
        # Has requires but no explicit backend
        for req in requires:
            for key, name in BACKEND_MAP.items():
                if key in req:
                    structure.build_systems.append(
                        BuildSystem(
                            name=name,
                            backend=None,
                            evidence=Evidence.INFERRED,
                            source_file="pyproject.toml",
                        )
                    )
                    break

    # Project metadata
    project = data.get("project", {})
    if project:
        structure.project_name = project.get("name")
        structure.version = project.get("version")
        structure.requires_python = project.get("requires-python")

        deps = project.get("dependencies", [])
        if deps:
            structure.dependencies = list(deps)

        # Entry points (console_scripts, gui_scripts)
        eps = project.get("scripts", {})
        for name, target_spec in eps.items():
            ep = _parse_entry_point_spec(name, target_spec, "console")
            if ep:
                structure.entry_points.append(ep)

        gui_eps = project.get("gui-scripts", {})
        for name, target_spec in gui_eps.items():
            ep = _parse_entry_point_spec(name, target_spec, "gui")
            if ep:
                structure.entry_points.append(ep)

        entry_point_groups = project.get("entry-points", {})
        for group_name, group_eps in entry_point_groups.items():
            for name, target_spec in group_eps.items():
                ep = _parse_entry_point_spec(name, target_spec, group_name)
                if ep:
                    structure.entry_points.append(ep)

    # Tool sections (poetry uses [tool.poetry])
    tool = data.get("tool", {})
    poetry = tool.get("poetry", {})
    if poetry:
        if not structure.project_name:
            structure.project_name = poetry.get("name")
        if not structure.version:
            structure.version = poetry.get("version")
        if not structure.dependencies:
            deps = poetry.get("dependencies", {})
            structure.dependencies = [f"{k}{v}" if isinstance(v, str) else k for k, v in deps.items() if k != "python"]
        if not any(b.name == "poetry" for b in structure.build_systems):
            structure.build_systems.append(
                BuildSystem(
                    name="poetry",
                    evidence=Evidence.OBSERVED,
                    source_file="pyproject.toml",
                )
            )
        # Poetry scripts
        poetry_scripts = poetry.get("scripts", {})
        for name, target_spec in poetry_scripts.items():
            ep = _parse_entry_point_spec(name, target_spec, "console")
            if ep:
                structure.entry_points.append(ep)


def _parse_entry_point_spec(name: str, target_spec: str, group: str) -> EntryPoint | None:
    """Parse 'module.submodule:attr' format entry point spec."""
    if ":" not in target_spec:
        return EntryPoint(name=name, module=target_spec, attr="", group=group)
    parts = target_spec.split(":", 1)
    module = parts[0]
    attr = parts[1] if len(parts) > 1 else ""
    return EntryPoint(name=name, module=module, attr=attr, group=group)


def _parse_setup_cfg(path: Path, structure: ProjectStructure) -> None:
    """Parse setup.cfg for additional metadata."""
    try:
        import configparser

        config = configparser.ConfigParser()
        config.read(path, encoding="utf-8")

        if config.has_section("metadata"):
            meta = config["metadata"]
            if not structure.project_name:
                structure.project_name = meta.get("name")
            if not structure.version:
                structure.version = meta.get("version")

        if config.has_section("options"):
            opts = config["options"]
            if not structure.requires_python:
                structure.requires_python = opts.get("python_requires")
            if not structure.dependencies:
                install_requires = opts.get("install_requires", "")
                if install_requires:
                    structure.dependencies = [r.strip() for r in install_requires.strip().splitlines() if r.strip()]

    except Exception as e:
        structure.errors.append(f"Failed to parse setup.cfg: {e}")


def _discover_source_roots(root: Path, all_files: list[tuple[Path, str]], structure: ProjectStructure) -> None:
    """Discover source roots and package names."""
    # Check for src/ layout
    src_dir = root / "src"
    if src_dir.is_dir():
        packages = []
        for item in sorted(src_dir.iterdir()):
            if item.is_dir() and (item / "__init__.py").exists() or item.is_dir() and _is_namespace_package(item):
                packages.append(item.name)
        structure.source_roots.append(SourceRoot(path="src", package_names=packages))

    # Check for flat layout (packages at root level)
    root_packages = []
    for item in sorted(root.iterdir()):
        if item.is_dir() and item.name not in SRC_PATTERNS and not item.name.startswith("."):
            if (item / "__init__.py").exists():
                root_packages.append(item.name)
    if root_packages:
        structure.source_roots.append(SourceRoot(path=".", package_names=root_packages))


def _is_namespace_package(path: Path) -> bool:
    """Check if a directory is a namespace package (no __init__.py but has .py files)."""
    has_py = False
    has_init = False
    try:
        for item in path.iterdir():
            if item.suffix == ".py":
                has_py = True
            if item.name == "__init__.py":
                has_init = True
    except OSError:
        pass
    return has_py and not has_init
