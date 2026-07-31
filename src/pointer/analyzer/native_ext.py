"""Composite native extension detection.

Detects native extension signals through multiple methods:
- Compiled files (.so, .pyd, .dylib)
- Wheel tags in wheel filenames
- Build backends (maturin, meson-python, scikit-build-core, setuptools extensions)
- Source references to Cython, CFFI, ctypes, pybind11, nanobind, PyO3
"""

from __future__ import annotations

import re
from pathlib import Path

from pointer.analyzer.filesystem import NATIVE_SUFFIXES, read_text_safely, safe_walk
from pointer.models import NativeExtAnalysis, NativeExtSignal, ProjectStructure

# Build backends that produce native extensions
NATIVE_BACKENDS = {
    "maturin": "maturin (Rust/PyO3 wheel builder)",
    "meson-python": "meson-python (Meson-based native builds)",
    "mesonpy": "meson-python (Meson-based native builds)",
    "scikit-build-core": "scikit-build-core (CMake-based native builds)",
    "scikit_build_core": "scikit-build-core (CMake-based native builds)",
    "setuptools-rust": "setuptools-rust (Rust extensions via setuptools)",
    "setuptools_rust": "setuptools-rust (Rust extensions via setuptools)",
}

# Source patterns that indicate native extension involvement
# (regex pattern, binding tool name)
SOURCE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bpyo3\b|\bPyO3\b", re.MULTILINE), "PyO3 (Rust↔Python bindings)"),
    (re.compile(r"\bpybind11\b", re.MULTILINE), "pybind11 (C++↔Python bindings)"),
    (re.compile(r"\bnanobind\b", re.MULTILINE), "nanobind (C++↔Python bindings)"),
    (re.compile(r"\bcffi\b", re.MULTILINE), "CFFI (C foreign function interface)"),
    (re.compile(r"\bfrom\s+ctypes\b|\bimport\s+ctypes\b", re.MULTILINE), "ctypes (C library calls)"),
    (re.compile(r"\bcython\b|\bCython\b", re.MULTILINE), "Cython (Python-like compiled language)"),
    (re.compile(r"\bcimport\b", re.MULTILINE), "Cython (cimport statement)"),
    (re.compile(r"\bext_modules?\b|\bExtModules?\b", re.MULTILINE), "setuptools extension module"),
]

# Wheel tag patterns
WHEEL_TAG_RE = re.compile(
    r"^(?P<distribution>[^-]+)-(?P<version>[^-]+)-(?P<python_tag>[^-]+)"
    r"-(?P<abi_tag>[^-]+)-(?P<platform_tag>[^-]+)\.whl$"
)

# Platform tags that indicate compiled wheels (not pure Python)
COMPILED_PLATFORM_TAGS = re.compile(r"^(linux|macos|win|manylinux|musllinux|emscripten)", re.I)


def detect(root: Path, structure: ProjectStructure) -> NativeExtAnalysis:
    """Detect native extension signals in the repository."""
    analysis = NativeExtAnalysis()
    all_files = safe_walk(root)

    # --- Check compiled files ---
    for fpath, rel in all_files:
        if fpath.suffix in NATIVE_SUFFIXES:
            analysis.signals.append(
                NativeExtSignal(
                    kind="compiled_file",
                    detail=f"Compiled extension: {fpath.name} ({fpath.suffix})",
                    file=rel,
                )
            )

    # --- Check wheel files ---
    for fpath, rel in all_files:
        if fpath.suffix == ".whl":
            match = WHEEL_TAG_RE.match(fpath.name)
            if match:
                platform_tag = match.group("platform_tag")
                abi_tag = match.group("abi_tag")
                if platform_tag != "any" or abi_tag != "none":
                    analysis.signals.append(
                        NativeExtSignal(
                            kind="wheel_tag",
                            detail=f"Compiled wheel: {fpath.name} (platform={platform_tag}, abi={abi_tag})",
                            file=rel,
                        )
                    )

    # --- Check build backends from pyproject.toml ---
    if structure.pyproject_data:
        build_sys = structure.pyproject_data.get("build-system", {})
        requires = build_sys.get("requires", [])
        backend = build_sys.get("build-backend", "")

        for req in requires + [backend]:
            req_lower = req.lower()
            for key, desc in NATIVE_BACKENDS.items():
                if key in req_lower:
                    analysis.signals.append(
                        NativeExtSignal(
                            kind="build_backend",
                            detail=f"Native build backend: {desc}",
                            file="pyproject.toml",
                        )
                    )
                    analysis.build_backends_native.append(key)
                    break

    # --- Check for C/C++ source files (potential native extensions) ---
    c_extensions = {".c", ".cpp", ".cxx", ".cc", ".C", ".h", ".hpp", ".hxx", ".hh"}
    rust_extensions = {".rs"}
    for fpath, rel in all_files:
        if fpath.suffix in c_extensions:
            analysis.signals.append(
                NativeExtSignal(
                    kind="source_reference",
                    detail=f"C/C++ source file: {rel}",
                    file=rel,
                )
            )
        elif fpath.suffix in rust_extensions:
            analysis.signals.append(
                NativeExtSignal(
                    kind="source_reference",
                    detail=f"Rust source file: {rel}",
                    file=rel,
                )
            )

    # --- Check source patterns for binding tools ---
    # Only scan Python and config files
    scan_extensions = {".py", ".pyx", ".pxd", ".toml", ".cfg", ".txt", ".cmake", ".in"}
    found_binding_tools: set[str] = set()
    for fpath, rel in all_files:
        if fpath.suffix not in scan_extensions:
            continue
        source = read_text_safely(fpath)
        if source is None:
            continue

        for pattern, tool_name in SOURCE_PATTERNS:
            if pattern.search(source):
                analysis.signals.append(
                    NativeExtSignal(
                        kind="source_reference",
                        detail=f"{tool_name} reference in {rel}",
                        file=rel,
                    )
                )
                binding_name = tool_name.split(" ")[0]
                found_binding_tools.add(binding_name)

    analysis.binding_tools = sorted(found_binding_tools)

    # --- Check for setup.py with ext_modules (even without pyproject) ---
    for fpath, rel in all_files:
        if fpath.name == "setup.py":
            source = read_text_safely(fpath)
            if source and "Extension" in source and "ext_modules" in source.lower():
                analysis.signals.append(
                    NativeExtSignal(
                        kind="build_backend",
                        detail="setuptools ext_modules declaration in setup.py",
                        file=rel,
                    )
                )

    # --- Final determination ---
    analysis.has_native_extensions = len(analysis.signals) > 0

    # Clean up: deduplicate signals by (kind, detail)
    seen: set[tuple[str, str]] = set()
    unique_signals: list[NativeExtSignal] = []
    for signal in analysis.signals:
        key = (signal.kind, signal.detail)
        if key not in seen:
            seen.add(key)
            unique_signals.append(signal)
    analysis.signals = unique_signals

    return analysis
