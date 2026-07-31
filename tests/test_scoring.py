"""Unit tests for the scoring/recommendation engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from pointer.analyzer import ast_scanner, discovery, metrics, native_ext, test_layout
from pointer.analyzer.deps_kb import disposition_for_imports
from pointer.analyzer.scoring import recommend, suggest_seams
from pointer.models import Target

FIXTURES = Path(__file__).parent / "fixtures"


def _full_analysis(root: Path, target: Target = Target.COMPARE):
    """Helper to run all analyzers for scoring tests."""
    structure = discovery.discover(root)
    ast_analysis = ast_scanner.scan_python(root)
    ne_analysis = native_ext.detect(root, structure)
    code_metrics = metrics.measure(root)
    test_info = test_layout.detect(root)
    dep_dispositions = disposition_for_imports(ast_analysis.external_imports, structure.dependencies)
    return structure, ast_analysis, ne_analysis, code_metrics, test_info, dep_dispositions


class TestScoringPurePython:
    @pytest.fixture
    def data(self):
        root = FIXTURES / "pure_python"
        s, a, ne, m, t, d = _full_analysis(root)
        return s, a, ne, m, t, d

    def test_recommendation_has_factors(self, data):
        s, a, ne, m, t, d = data
        rec = recommend(Target.RUST, s, a, ne, m, t, d)
        assert len(rec.factors) > 0

    def test_recommendation_has_rationale(self, data):
        s, a, ne, m, t, d = data
        rec = recommend(Target.COMPARE, s, a, ne, m, t, d)
        assert len(rec.rationale) > 0

    def test_recommendation_has_caveats(self, data):
        s, a, ne, m, t, d = data
        rec = recommend(Target.COMPARE, s, a, ne, m, t, d)
        assert len(rec.caveats) > 0

    def test_scores_are_integers(self, data):
        s, a, ne, m, t, d = data
        rec = recommend(Target.COMPARE, s, a, ne, m, t, d)
        assert isinstance(rec.rust_score, int)
        assert isinstance(rec.cpp_score, int)
        assert isinstance(rec.stay_python_score, int)

    def test_pure_python_favors_native_for_small_codebase(self, data):
        s, a, ne, m, t, d = data
        rec = recommend(Target.COMPARE, s, a, ne, m, t, d)
        # Small codebase, few blockers → should lean positive
        assert rec.rust_score + rec.cpp_score > rec.stay_python_score


class TestScoringDynamicRepo:
    @pytest.fixture
    def data(self):
        root = FIXTURES / "dynamic"
        s, a, ne, m, t, d = _full_analysis(root)
        return s, a, ne, m, t, d

    def test_dynamic_blockers_lower_scores(self, data):
        s, a, ne, m, t, d = data
        rec = recommend(Target.RUST, s, a, ne, m, t, d)
        # Dynamic blockers should create a factor
        blocker_factors = [f for f in rec.factors if f.name == "dynamic_constructs"]
        assert len(blocker_factors) == 1
        assert blocker_factors[0].score < 0


class TestScoringUnknownDeps:
    def test_unknown_deps_produce_no_disposition(self):
        from pointer.analyzer.deps_kb import lookup

        result = lookup("nonexistent_package_xyz123")
        assert result is None

    def test_known_deps_produce_disposition(self):
        from pointer.analyzer.deps_kb import lookup

        result = lookup("numpy")
        assert result is not None
        assert result.disposition == "ffi_wrap"

    def test_unknown_deps_in_list_marked_unknown(self):
        from pointer.analyzer.deps_kb import disposition_for_imports

        results = disposition_for_imports(["numpy", "totally_fake_pkg"], [])
        unknown_results = [r for r in results if r.disposition == "unknown"]
        assert len(unknown_results) == 1
        assert unknown_results[0].name == "totally_fake_pkg"


class TestMigrationSeams:
    def test_seams_returned(self):
        root = FIXTURES / "pure_python"
        s, a, ne, m, t, d = _full_analysis(root)
        seams = suggest_seams(s, a, d, ne)
        assert isinstance(seams, list)
