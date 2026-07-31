"""Target recommendation scoring engine.

Produces a transparent Rust-vs-C++-vs-hybrid-vs-stay-Python recommendation
with explicit factors and scores. Allows an inconclusive result.
Does not promise performance gains without evidence.
"""

from __future__ import annotations

from pointer.models import (
    AstAnalysis,
    CodeMetrics,
    Confidence,
    DepDisposition,
    MigrationSeam,
    NativeExtAnalysis,
    ProjectStructure,
    Recommendation,
    ScoreFactor,
    Target,
    TestAnalysis,
)


def recommend(
    target: Target,
    structure: ProjectStructure,
    ast_analysis: AstAnalysis,
    native_ext: NativeExtAnalysis,
    metrics: CodeMetrics,
    tests: TestAnalysis,
    dep_dispositions: list[DepDisposition],
) -> Recommendation:
    """Compute a target recommendation."""
    factors: list[ScoreFactor] = []

    # --- Factor: Codebase size ---
    if metrics.total_py_lines > 0:
        if metrics.total_py_lines < 500:
            factors.append(
                ScoreFactor(
                    name="codebase_size",
                    score=1,
                    rust_weight=1,
                    cpp_weight=1,
                    reason=f"Small codebase ({metrics.total_py_lines} Python lines) — feasible to port in entirety.",
                )
            )
        elif metrics.total_py_lines < 5000:
            factors.append(
                ScoreFactor(
                    name="codebase_size",
                    score=0,
                    rust_weight=0,
                    cpp_weight=0,
                    reason=(
                        f"Medium codebase ({metrics.total_py_lines} Python lines) — "
                        "porting is a significant but tractable project."
                    ),
                )
            )
        else:
            factors.append(
                ScoreFactor(
                    name="codebase_size",
                    score=-1,
                    rust_weight=-1,
                    cpp_weight=-1,
                    reason=(
                        f"Large codebase ({metrics.total_py_lines} Python lines) — consider incremental/hybrid porting."
                    ),
                )
            )
    else:
        factors.append(
            ScoreFactor(
                name="codebase_size",
                score=0,
                reason="No Python source files detected.",
            )
        )

    # --- Factor: Dynamic blockers ---
    high_blockers = [b for b in ast_analysis.dynamic_blockers if b.severity == "high"]
    medium_blockers = [b for b in ast_analysis.dynamic_blockers if b.severity == "medium"]
    blocker_score = -min(len(high_blockers) * 2 + len(medium_blockers), 5)
    if ast_analysis.dynamic_blockers:
        factors.append(
            ScoreFactor(
                name="dynamic_constructs",
                score=blocker_score,
                rust_weight=0,
                cpp_weight=0,
                reason=(
                    f"{len(high_blockers)} high-severity and {len(medium_blockers)} "
                    "medium-severity dynamic constructs detected "
                    "(eval/exec/metaclass/monkeypatch). These complicate any native port."
                ),
            )
        )
    else:
        factors.append(
            ScoreFactor(
                name="dynamic_constructs",
                score=1,
                rust_weight=1,
                cpp_weight=1,
                reason="No significant dynamic language blockers detected — code is more portable.",
            )
        )

    # --- Factor: Type annotation coverage ---
    if ast_analysis.type_annotation_coverage > 0:
        coverage = ast_analysis.type_annotation_coverage
        if coverage > 0.7:
            factors.append(
                ScoreFactor(
                    name="type_coverage",
                    score=1,
                    rust_weight=1,
                    cpp_weight=0,
                    reason=(
                        f"High type annotation coverage ({coverage:.0%}) — "
                        "types ease porting to statically typed languages."
                    ),
                )
            )
        elif coverage > 0.3:
            factors.append(
                ScoreFactor(
                    name="type_coverage",
                    score=0,
                    reason=f"Moderate type annotation coverage ({coverage:.0%}).",
                )
            )
        else:
            factors.append(
                ScoreFactor(
                    name="type_coverage",
                    score=-1,
                    rust_weight=0,
                    cpp_weight=0,
                    reason=(
                        f"Low type annotation coverage ({coverage:.0%}) — "
                        "significant type inference work needed before porting."
                    ),
                )
            )

    # --- Factor: Native extension experience ---
    if native_ext.has_native_extensions:
        if "maturin" in native_ext.build_backends_native or "PyO3" in " ".join(native_ext.binding_tools):
            factors.append(
                ScoreFactor(
                    name="native_experience",
                    score=2,
                    rust_weight=2,
                    cpp_weight=0,
                    reason="Project already uses Rust/PyO3 (maturin) — team has native extension experience.",
                )
            )
        elif any(b in native_ext.build_backends_native for b in ["scikit-build-core", "meson-python"]):
            factors.append(
                ScoreFactor(
                    name="native_experience",
                    score=2,
                    rust_weight=1,
                    cpp_weight=2,
                    reason="Project already uses native build backends — team has native extension experience.",
                )
            )
        else:
            factors.append(
                ScoreFactor(
                    name="native_experience",
                    score=1,
                    rust_weight=1,
                    cpp_weight=1,
                    reason="Native extension signals detected — some existing native experience.",
                )
            )

    # --- Factor: Dependency disposition ---
    known_deps = [d for d in dep_dispositions if d.disposition != "unknown"]
    direct_replacements = [d for d in known_deps if d.disposition == "direct_replacement"]
    keep_python_deps = [d for d in known_deps if d.disposition == "keep_python"]
    unknown_deps = [d for d in dep_dispositions if d.disposition == "unknown"]

    if known_deps:
        if len(direct_replacements) > len(keep_python_deps):
            factors.append(
                ScoreFactor(
                    name="dependency_landscape",
                    score=1,
                    rust_weight=1,
                    cpp_weight=0,
                    reason=f"{len(direct_replacements)} dependencies have direct native equivalents.",
                )
            )
        elif len(keep_python_deps) > len(known_deps) / 2:
            factors.append(
                ScoreFactor(
                    name="dependency_landscape",
                    score=-2,
                    rust_weight=-1,
                    cpp_weight=-1,
                    reason=(
                        f"{len(keep_python_deps)} dependencies are tightly coupled to Python "
                        "(Django, PyTorch, etc.) — consider keeping those modules in Python."
                    ),
                )
            )
        else:
            factors.append(
                ScoreFactor(
                    name="dependency_landscape",
                    score=0,
                    reason=f"{len(known_deps)} known dependencies; mixed portability.",
                )
            )

    if unknown_deps:
        factors.append(
            ScoreFactor(
                name="unknown_dependencies",
                score=0,
                reason=(
                    f"{len(unknown_deps)} dependencies are not in Pointer's knowledge base — manual research required."
                ),
            )
        )

    # --- Factor: Test coverage / oracle readiness ---
    if tests.oracle_readiness == "high":
        factors.append(
            ScoreFactor(
                name="test_oracle",
                score=1,
                rust_weight=1,
                cpp_weight=1,
                reason="Strong test suite — enables reliable differential verification.",
            )
        )
    elif tests.oracle_readiness == "low":
        factors.append(
            ScoreFactor(
                name="test_oracle",
                score=-1,
                rust_weight=0,
                cpp_weight=0,
                reason="Weak or absent test suite — differential verification will be harder.",
            )
        )

    # --- Calculate scores ---
    base_score = sum(f.score for f in factors)
    rust_score = base_score + sum(f.rust_weight for f in factors)
    cpp_score = base_score + sum(f.cpp_weight for f in factors)
    stay_python_score = -base_score

    # --- Determine recommendation ---
    if target == Target.RUST:
        rec_target = "rust"
        rec_confidence = (
            Confidence.HIGH if rust_score > 2 else (Confidence.MEDIUM if rust_score > -2 else Confidence.LOW)
        )
        rationale = _build_rust_rationale(factors)
    elif target == Target.CPP:
        rec_target = "cpp"
        rec_confidence = Confidence.HIGH if cpp_score > 2 else (Confidence.MEDIUM if cpp_score > -2 else Confidence.LOW)
        rationale = _build_cpp_rationale(factors)
    else:
        # compare mode
        if rust_score > cpp_score + 2:
            rec_target = "rust"
        elif cpp_score > rust_score + 2:
            rec_target = "cpp"
        elif rust_score > 0 or cpp_score > 0:
            rec_target = "hybrid"
        elif stay_python_score > 0:
            rec_target = "stay_python"
        else:
            rec_target = "inconclusive"

        rec_confidence = (
            Confidence.HIGH
            if max(rust_score, cpp_score) > 2
            else (Confidence.MEDIUM if max(rust_score, cpp_score) > -2 else Confidence.LOW)
        )
        rationale = _build_compare_rationale(factors, rust_score, cpp_score, stay_python_score)

    # Caveats
    caveats: list[str] = []
    caveats.append(
        "This is a static analysis recommendation based on repository signals, not a guarantee of porting success."
    )
    if unknown_deps:
        caveats.append(f"{len(unknown_deps)} dependencies require manual portability research.")
    if high_blockers:
        caveats.append(f"{len(high_blockers)} high-severity dynamic constructs must be refactored before porting.")
    caveats.append("Pointer does not predict performance gains — benchmarking is required after porting.")

    return Recommendation(
        target=rec_target,
        confidence=rec_confidence,
        rust_score=rust_score,
        cpp_score=cpp_score,
        stay_python_score=stay_python_score,
        factors=factors,
        rationale=rationale,
        caveats=caveats,
    )


def _build_rust_rationale(factors: list[ScoreFactor]) -> str:
    positive = [f for f in factors if f.score + f.rust_weight > 0]
    negative = [f for f in factors if f.score + f.rust_weight < 0]
    lines = ["Rust target assessment:"]
    if positive:
        lines.append("Favorable: " + "; ".join(f.reason for f in positive[:3]))
    if negative:
        lines.append("Challenges: " + "; ".join(f.reason for f in negative[:3]))
    lines.append(
        "Rust offers structural memory safety (borrow checker), unified build system (cargo), "
        "and mature Python bindings (PyO3/maturin)."
    )
    return " ".join(lines)


def _build_cpp_rationale(factors: list[ScoreFactor]) -> str:
    positive = [f for f in factors if f.score + f.cpp_weight > 0]
    negative = [f for f in factors if f.score + f.cpp_weight < 0]
    lines = ["C++ target assessment:"]
    if positive:
        lines.append("Favorable: " + "; ".join(f.reason for f in positive[:3]))
    if negative:
        lines.append("Challenges: " + "; ".join(f.reason for f in negative[:3]))
    lines.append(
        "C++ offers maximum platform control, existing ecosystem integration, and rr debugger support. "
        "Requires disciplined use of sanitizers (ASan/MSan/UBSan)."
    )
    return " ".join(lines)


def _build_compare_rationale(factors: list[ScoreFactor], rust_score: int, cpp_score: int, stay_score: int) -> str:
    lines = ["Comparative assessment:"]
    lines.append(f"Rust score: {rust_score}, C++ score: {cpp_score}, Stay-Python score: {stay_score}.")
    if rust_score > cpp_score:
        lines.append("Rust is favored due to structural memory safety, unified tooling, and ecosystem momentum.")
    elif cpp_score > rust_score:
        lines.append("C++ is favored when existing native dependencies or platform constraints require it.")
    else:
        lines.append("Both targets are comparably viable; choose based on team expertise.")
    if stay_score > 0:
        lines.append("However, signals suggest staying in Python or using a hybrid approach may be more pragmatic.")
    return " ".join(lines)


def suggest_seams(
    structure: ProjectStructure,
    ast_analysis: AstAnalysis,
    dep_dispositions: list[DepDisposition],
    native_ext: NativeExtAnalysis,
) -> list[MigrationSeam]:
    """Suggest migration seams based on module boundaries and dependencies."""
    seams: list[MigrationSeam] = []

    # Group external imports by likely module
    module_deps: dict[str, list[str]] = {}
    for imp in ast_analysis.imports:
        # Extract module prefix from file path
        file_parts = imp.file.split("/")
        module = "/".join(file_parts[:-1]) if len(file_parts) > 1 else "root"
        module_deps.setdefault(module, [])
        if imp.module not in STDLIB_MODULES_SET and imp.module not in module_deps[module]:
            module_deps[module].append(imp.module)

    # Find modules with high dependency concentration for porting priority
    for module, deps in sorted(module_deps.items(), key=lambda x: -len(x[1])):
        if len(deps) < 2:
            continue

        # Find blockers in this module
        blockers_in_module = [b.category for b in ast_analysis.dynamic_blockers if b.file.startswith(module)]

        # Determine priority
        known_deps_count = sum(1 for d in dep_dispositions if d.name in deps and d.disposition != "unknown")
        keep_python_deps = [d.name for d in dep_dispositions if d.name in deps and d.disposition == "keep_python"]

        if keep_python_deps:
            priority = "low"
            reason = f"Contains Python-coupled dependencies: {', '.join(keep_python_deps)}"
        elif blockers_in_module:
            priority = "low"
            reason = f"Contains dynamic blockers: {', '.join(set(blockers_in_module[:3]))}"
        elif known_deps_count >= 2:
            priority = "high"
            reason = (
                f"High dependency concentration ({len(deps)} imports, {known_deps_count} with known native equivalents)"
            )
        else:
            priority = "medium"
            reason = f"Module with {len(deps)} external dependencies"

        seams.append(
            MigrationSeam(
                module=module,
                reason=reason,
                priority=priority,
                dependencies=deps[:10],
                blockers=list(set(blockers_in_module[:5])),
            )
        )

    return seams[:15]  # Top 15 seams


# Subset of stdlib for seam analysis
STDLIB_MODULES_SET = frozenset(
    {
        "abc",
        "argparse",
        "ast",
        "asyncio",
        "base64",
        "collections",
        "concurrent",
        "contextlib",
        "copy",
        "csv",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "functools",
        "hashlib",
        "html",
        "http",
        "importlib",
        "inspect",
        "io",
        "itertools",
        "json",
        "logging",
        "math",
        "os",
        "pathlib",
        "pickle",
        "re",
        "shutil",
        "signal",
        "socket",
        "sqlite3",
        "ssl",
        "statistics",
        "string",
        "struct",
        "subprocess",
        "sys",
        "tempfile",
        "textwrap",
        "threading",
        "time",
        "traceback",
        "typing",
        "unittest",
        "urllib",
        "uuid",
        "warnings",
        "weakref",
        "xml",
        "zipfile",
        "zlib",
        "tomllib",
        "secrets",
        "platform",
        "configparser",
    }
)
