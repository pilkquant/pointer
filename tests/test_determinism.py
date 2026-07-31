"""Golden/determinism tests: same input → same output."""

from __future__ import annotations

import json
from pathlib import Path

from pointer.models import Target
from pointer.pipeline import analyze
from pointer.report.json_out import to_json

FIXTURES = Path(__file__).parent / "fixtures"


class TestDeterminism:
    """Reports must be deterministic for the same input (ignoring timestamps)."""

    def _strip_variable_fields(self, data: dict) -> dict:
        """Remove fields that change between runs (timestamps)."""
        data = json.loads(json.dumps(data))  # deep copy
        if "analysis_timestamp" in data:
            del data["analysis_timestamp"]
        return data

    def test_json_deterministic_pure_python(self):
        report1 = analyze(FIXTURES / "pure_python", Target.COMPARE)
        report2 = analyze(FIXTURES / "pure_python", Target.COMPARE)

        data1 = self._strip_variable_fields(json.loads(to_json(report1)))
        data2 = self._strip_variable_fields(json.loads(to_json(report2)))

        assert data1 == data2

    def test_json_deterministic_dynamic(self):
        report1 = analyze(FIXTURES / "dynamic", Target.RUST)
        report2 = analyze(FIXTURES / "dynamic", Target.RUST)

        data1 = self._strip_variable_fields(json.loads(to_json(report1)))
        data2 = self._strip_variable_fields(json.loads(to_json(report2)))

        assert data1 == data2

    def test_json_deterministic_native(self):
        report1 = analyze(FIXTURES / "native_ext", Target.CPP)
        report2 = analyze(FIXTURES / "native_ext", Target.CPP)

        data1 = self._strip_variable_fields(json.loads(to_json(report1)))
        data2 = self._strip_variable_fields(json.loads(to_json(report2)))

        assert data1 == data2

    def test_schema_version_stable(self):
        report = analyze(FIXTURES / "pure_python", Target.COMPARE)
        assert report.schema_version == "0.1.0"

    def test_target_reflected_in_report(self):
        for target in Target:
            report = analyze(FIXTURES / "pure_python", target)
            assert report.target == target.value
