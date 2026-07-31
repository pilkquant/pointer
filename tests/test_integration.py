"""Integration tests: full pipeline on fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pointer.models import Target
from pointer.pipeline import analyze
from pointer.report.json_out import to_json
from pointer.report.markdown import to_markdown

FIXTURES = Path(__file__).parent / "fixtures"


class TestPurePythonIntegration:
    @pytest.fixture
    def report(self):
        return analyze(FIXTURES / "pure_python", Target.COMPARE)

    def test_report_has_schema_version(self, report):
        assert report.schema_version == "0.1.0"

    def test_report_has_timestamp(self, report):
        assert len(report.analysis_timestamp) > 0

    def test_structure_present(self, report):
        assert report.structure is not None
        assert report.structure.project_name == "tinylib"

    def test_ast_analysis_present(self, report):
        assert report.ast_analysis is not None
        assert report.ast_analysis.total_py_files > 0

    def test_metrics_present(self, report):
        assert report.metrics is not None
        assert report.metrics.total_py_lines > 0

    def test_tests_present(self, report):
        assert report.tests is not None
        assert len(report.tests.test_files) > 0

    def test_recommendation_present(self, report):
        assert report.recommendation is not None
        assert report.recommendation.target in ("rust", "cpp", "hybrid", "stay_python", "inconclusive")

    def test_json_serializable(self, report):
        data = to_json(report)
        parsed = json.loads(data)
        assert parsed["schema_version"] == "0.1.0"

    def test_markdown_generates(self, report):
        md = to_markdown(report)
        assert "# Pointer Portability Report" in md
        assert "tinylib" in md


class TestDynamicIntegration:
    @pytest.fixture
    def report(self):
        return analyze(FIXTURES / "dynamic", Target.COMPARE)

    def test_dynamic_blockers_in_report(self, report):
        assert report.ast_analysis is not None
        cats = [b.category for b in report.ast_analysis.dynamic_blockers]
        assert "eval" in cats

    def test_recommendation_reflects_blockers(self, report):
        rec = report.recommendation
        assert rec is not None
        blocker_factors = [f for f in rec.factors if f.name == "dynamic_constructs"]
        assert len(blocker_factors) == 1
        assert blocker_factors[0].score < 0


class TestNativeExtIntegration:
    @pytest.fixture
    def report(self):
        return analyze(FIXTURES / "native_ext", Target.COMPARE)

    def test_native_detected(self, report):
        assert report.native_ext is not None
        assert report.native_ext.has_native_extensions is True

    def test_maturin_in_report(self, report):
        assert "maturin" in report.native_ext.build_backends_native


class TestMalformedIntegration:
    @pytest.fixture
    def report(self):
        return analyze(FIXTURES / "malformed", Target.COMPARE)

    def test_syntax_errors_handled(self, report):
        assert report.ast_analysis is not None
        assert len(report.ast_analysis.files_with_syntax_errors) > 0

    def test_report_still_generated(self, report):
        assert report.summary
        assert report.recommendation is not None

    def test_warning_emitted(self, report):
        assert len(report.warnings) > 0
