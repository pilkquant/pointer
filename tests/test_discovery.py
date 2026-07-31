"""Unit tests for the discovery analyzer."""

from __future__ import annotations

from pathlib import Path

import pytest

from pointer.analyzer import discovery

FIXTURES = Path(__file__).parent / "fixtures"


class TestPurePythonDiscovery:
    """Test discovery on the pure_python fixture."""

    @pytest.fixture
    def root(self):
        return FIXTURES / "pure_python"

    @pytest.fixture
    def structure(self, root):
        return discovery.discover(root)

    def test_finds_pyproject(self, structure):
        kinds = [f.kind for f in structure.files if f.kind == "pyproject"]
        assert len(kinds) == 1

    def test_project_name(self, structure):
        assert structure.project_name == "tinylib"

    def test_version(self, structure):
        assert structure.version == "0.1.0"

    def test_requires_python(self, structure):
        assert structure.requires_python == ">=3.11"

    def test_dependencies(self, structure):
        assert "requests>=2.0" in structure.dependencies
        assert "pyyaml" in structure.dependencies

    def test_build_system_hatch(self, structure):
        names = [b.name for b in structure.build_systems]
        assert "hatch" in names

    def test_entry_points(self, structure):
        assert len(structure.entry_points) >= 1
        ep = structure.entry_points[0]
        assert ep.name == "tinylib"
        assert ep.module == "tinylib.cli"
        assert ep.attr == "main"

    def test_source_roots(self, structure):
        assert len(structure.source_roots) >= 1
        # Should find src layout
        src_roots = [sr for sr in structure.source_roots if sr.path == "src"]
        assert len(src_roots) == 1
        assert "tinylib" in src_roots[0].package_names


class TestMalformedRepo:
    """Test discovery on malformed repo (no pyproject)."""

    @pytest.fixture
    def root(self):
        return FIXTURES / "malformed"

    @pytest.fixture
    def structure(self, root):
        return discovery.discover(root)

    def test_no_pyproject(self, structure):
        assert structure.project_name is None
        assert structure.version is None

    def test_no_build_systems(self, structure):
        assert len(structure.build_systems) == 0


class TestDynamicRepo:
    """Test discovery on dynamic repo."""

    @pytest.fixture
    def root(self):
        return FIXTURES / "dynamic"

    @pytest.fixture
    def structure(self, root):
        return discovery.discover(root)

    def test_build_system_setuptools(self, structure):
        names = [b.name for b in structure.build_systems]
        assert "setuptools" in names

    def test_dependencies(self, structure):
        assert "django" in " ".join(structure.dependencies)
