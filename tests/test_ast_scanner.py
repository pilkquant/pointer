"""Unit tests for the AST scanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from pointer.analyzer import ast_scanner

FIXTURES = Path(__file__).parent / "fixtures"


class TestPurePythonAST:
    @pytest.fixture
    def root(self):
        return FIXTURES / "pure_python"

    @pytest.fixture
    def analysis(self, root):
        return ast_scanner.scan_python(root)

    def test_finds_python_files(self, analysis):
        assert analysis.total_py_files >= 3

    def test_no_syntax_errors(self, analysis):
        assert len(analysis.files_with_syntax_errors) == 0

    def test_finds_stdlib_imports(self, analysis):
        assert "hashlib" in analysis.stdlib_imports
        assert "json" in analysis.stdlib_imports

    def test_no_high_severity_blockers(self, analysis):
        high = [b for b in analysis.dynamic_blockers if b.severity == "high"]
        assert len(high) == 0

    def test_type_annotation_coverage(self, analysis):
        assert analysis.type_annotation_coverage > 0


class TestDynamicPythonAST:
    @pytest.fixture
    def root(self):
        return FIXTURES / "dynamic"

    @pytest.fixture
    def analysis(self, root):
        return ast_scanner.scan_python(root)

    def test_detects_eval(self, analysis):
        cats = [b.category for b in analysis.dynamic_blockers]
        assert "eval" in cats

    def test_detects_exec(self, analysis):
        cats = [b.category for b in analysis.dynamic_blockers]
        assert "exec" in cats

    def test_detects_metaclass(self, analysis):
        cats = [b.category for b in analysis.dynamic_blockers]
        assert "metaclass" in cats

    def test_detects_getattr(self, analysis):
        cats = [b.category for b in analysis.dynamic_blockers]
        assert "__getattr__" in cats

    def test_detects_monkeypatch(self, analysis):
        cats = [b.category for b in analysis.dynamic_blockers]
        assert "monkeypatch" in cats

    def test_detects_dynamic_import(self, analysis):
        cats = [b.category for b in analysis.dynamic_blockers]
        assert "importlib.import_module" in cats

    def test_detects_compile(self, analysis):
        cats = [b.category for b in analysis.dynamic_blockers]
        assert "compile" in cats


class TestMalformedAST:
    @pytest.fixture
    def root(self):
        return FIXTURES / "malformed"

    @pytest.fixture
    def analysis(self, root):
        return ast_scanner.scan_python(root)

    def test_syntax_error_recorded(self, analysis):
        assert len(analysis.files_with_syntax_errors) >= 1

    def test_valid_file_still_scanned(self, analysis):
        # main.py should still be scanned even though broken.py fails
        assert analysis.total_py_files >= 2
