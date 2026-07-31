"""Tests for report quality — evidence/inference/confidence taxonomy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pointer.models import Confidence, Evidence, Target
from pointer.pipeline import analyze
from pointer.report.json_out import to_json
from pointer.report.markdown import to_markdown

FIXTURES = Path(__file__).parent / "fixtures"


class TestEvidenceTaxonomy:
    """Reports must distinguish evidence, inference, confidence, and unknowns."""

    @pytest.fixture
    def report(self):
        return analyze(FIXTURES / "pure_python", Target.COMPARE)

    def test_json_has_evidence_values(self, report):
        """Build system evidence should use Evidence enum values."""
        data = json.loads(to_json(report))
        for bs in data["structure"]["build_systems"]:
            assert bs["evidence"] in [e.value for e in Evidence]

    def test_json_has_confidence_values(self, report):
        """Recommendation confidence should use Confidence enum values."""
        data = json.loads(to_json(report))
        assert data["recommendation"]["confidence"] in [c.value for c in Confidence]

    def test_dep_dispositions_have_provenance(self, report):
        """Every dependency disposition must have provenance."""
        for dep in report.dependency_dispositions:
            assert len(dep.provenance) > 0

    def test_unknown_deps_marked_unknown(self, report):
        """Deps not in KB should be 'unknown', not fabricated."""
        unknown_deps = [d for d in report.dependency_dispositions if d.disposition == "unknown"]
        for dep in unknown_deps:
            assert dep.confidence == Confidence.LOW
            assert "not in" in dep.provenance.lower() or "manual" in dep.provenance.lower()

    def test_markdown_has_evidence_section(self, report):
        """Markdown must include evidence/inference/unknown section."""
        md = to_markdown(report)
        assert "Evidence" in md or "Observed" in md

    def test_recommendation_has_caveats(self, report):
        """Recommendation must include caveats."""
        assert len(report.recommendation.caveats) > 0
        # Must mention this is static analysis
        assert any("static" in c.lower() for c in report.recommendation.caveats)

    def test_factors_have_reasons(self, report):
        """Every scoring factor must explain its reasoning."""
        for factor in report.recommendation.factors:
            assert len(factor.reason) > 10  # non-trivial explanation

    def test_markdown_mentions_safety(self, report):
        """Markdown should mention the safety model."""
        md = to_markdown(report)
        assert "static analysis" in md.lower()

    def test_no_performance_promises_without_evidence(self, report):
        """Reports must not promise performance gains."""
        md = to_markdown(report)
        # Check for caveats about benchmarking
        assert "benchmark" in md.lower() or "performance" not in md.lower()
