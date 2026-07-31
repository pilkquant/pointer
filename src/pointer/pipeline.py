"""Analysis pipeline — orchestrates all analyzers into a complete report."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pointer import __version__
from pointer.analyzer import ast_scanner, discovery, metrics, native_ext, scoring, test_layout
from pointer.analyzer.deps_kb import disposition_for_imports
from pointer.models import AnalysisReport, Target


def analyze(root: Path, target: Target = Target.COMPARE) -> AnalysisReport:
    """Run the full analysis pipeline and return a complete report.

    This is the main entry point for analysis. It never imports or executes
    code from the target repository.
    """
    report = AnalysisReport(
        schema_version="0.1.0",
        pointer_version=__version__,
        target=target.value,
        analysis_timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        root_path=str(root.resolve()),
    )

    # Stage 1: Discovery
    structure = discovery.discover(root)
    report.structure = structure

    # Stage 2: AST scanning
    ast_analysis = ast_scanner.scan_python(root)
    report.ast_analysis = ast_analysis

    # Stage 3: Native extension detection
    ne_analysis = native_ext.detect(root, structure)
    report.native_ext = ne_analysis

    # Stage 4: Code metrics
    code_metrics = metrics.measure(root)
    report.metrics = code_metrics

    # Stage 5: Test layout
    test_info = test_layout.detect(root)
    report.tests = test_info

    # Stage 6: Dependency dispositions
    dep_dispositions = disposition_for_imports(ast_analysis.external_imports, structure.dependencies)
    report.dependency_dispositions = dep_dispositions

    # Stage 7: Recommendation
    recommendation = scoring.recommend(
        target,
        structure,
        ast_analysis,
        ne_analysis,
        code_metrics,
        test_info,
        dep_dispositions,
    )
    report.recommendation = recommendation

    # Stage 8: Migration seams
    seams = scoring.suggest_seams(structure, ast_analysis, dep_dispositions, ne_analysis)
    report.migration_seams = seams

    # Generate summary
    report.summary = _build_summary(report)

    # Collect warnings
    if ast_analysis.files_with_syntax_errors:
        report.warnings.append(
            f"{len(ast_analysis.files_with_syntax_errors)} file(s) have syntax "
            "errors and were skipped during AST analysis."
        )
    if not structure.build_systems:
        report.warnings.append("No build system detected — this may be a non-package Python project.")

    return report


def _build_summary(report: AnalysisReport) -> str:
    """Build a concise summary paragraph."""
    parts: list[str] = []

    struct = report.structure
    metrics_data = report.metrics
    ast_data = report.ast_analysis

    if struct and struct.project_name:
        parts.append(f"**{struct.project_name}**")
    else:
        parts.append("Python repository")

    if metrics_data:
        parts.append(f"({metrics_data.total_py_files} Python files, {metrics_data.total_py_lines} lines)")

    if report.native_ext:
        if report.native_ext.has_native_extensions:
            parts.append("with native extension signals")
        else:
            parts.append("pure Python")

    if ast_data and ast_data.dynamic_blockers:
        high_count = sum(1 for b in ast_data.dynamic_blockers if b.severity == "high")
        if high_count:
            parts.append(f"and {high_count} high-severity dynamic blocker(s)")

    if report.recommendation:
        rec = report.recommendation
        parts.append(f". Recommendation: **{rec.target}** (confidence: {rec.confidence.value})")

    return " ".join(parts) + "."
