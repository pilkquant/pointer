"""Unit tests for native extension detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from pointer.analyzer import discovery, native_ext

FIXTURES = Path(__file__).parent / "fixtures"


class TestNativeExtDetection:
    @pytest.fixture
    def root(self):
        return FIXTURES / "native_ext"

    @pytest.fixture
    def structure(self, root):
        return discovery.discover(root)

    @pytest.fixture
    def analysis(self, root, structure):
        return native_ext.detect(root, structure)

    def test_has_native_extensions(self, analysis):
        assert analysis.has_native_extensions is True

    def test_maturin_backend(self, analysis):
        assert "maturin" in analysis.build_backends_native

    def test_binding_tools_detected(self, analysis):
        # Should find cffi and/or ctypes references
        assert len(analysis.binding_tools) > 0

    def test_rust_source_detected(self, analysis):
        kinds = [s.kind for s in analysis.signals if s.kind == "source_reference"]
        assert len(kinds) >= 2  # .rs and .c

    def test_pyo3_reference(self, analysis):
        details = " ".join(s.detail for s in analysis.signals)
        assert "PyO3" in details or "pyo3" in details.lower()


class TestPurePythonNoNative:
    @pytest.fixture
    def root(self):
        return FIXTURES / "pure_python"

    @pytest.fixture
    def structure(self, root):
        return discovery.discover(root)

    @pytest.fixture
    def analysis(self, root, structure):
        return native_ext.detect(root, structure)

    def test_no_native_extensions(self, analysis):
        assert analysis.has_native_extensions is False

    def test_no_signals(self, analysis):
        assert len(analysis.signals) == 0
