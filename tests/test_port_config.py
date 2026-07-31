"""Tests for port configuration parsing — pointer.toml, oracle cases, normalization."""

from __future__ import annotations

import pytest

from pointer.porting.config import (
    NormalizationConfig,
    OracleCase,
    auto_discover_entry_points,
    load_config,
    parse_config,
)


class TestNormalization:
    def test_strip_trailing_whitespace(self):
        norm = NormalizationConfig(strip_trailing_whitespace=True)
        assert norm.normalize("hello   \nworld  ") == "hello\nworld"

    def test_normalize_newlines(self):
        norm = NormalizationConfig(normalize_newlines=True)
        assert norm.normalize("hello\r\nworld\r") == "hello\nworld\n"

    def test_strip_color_codes(self):
        norm = NormalizationConfig(strip_color_codes=True)
        assert norm.normalize("\x1b[32mgreen\x1b[0m") == "green"

    def test_sort_lines(self):
        norm = NormalizationConfig(sort_lines=True)
        assert norm.normalize("c\na\nb") == "a\nb\nc"

    def test_default_config(self):
        norm = NormalizationConfig()
        assert norm.strip_trailing_whitespace is True
        assert norm.normalize_newlines is True


class TestOracleCase:
    def test_basic(self):
        case = OracleCase(name="test", command=["python", "script.py"])
        assert case.name == "test"
        assert case.command == ["python", "script.py"]
        assert case.expected_exit == 0
        assert case.has_dynamic_expected is True

    def test_with_expected_output(self):
        case = OracleCase(
            name="test",
            command=["python", "script.py"],
            expected_stdout="42\n",
        )
        assert case.has_dynamic_expected is False

    def test_to_from_dict(self):
        case = OracleCase(name="test", command=["python", "script.py"], stdin="input")
        d = case.to_dict()
        case2 = OracleCase.from_dict(d)
        assert case2.name == case.name
        assert case2.command == case.command
        assert case2.stdin == case.stdin


class TestParseConfig:
    def test_empty(self):
        config = parse_config({})
        assert config.target == "rust"
        assert config.oracle_cases == []

    def test_target(self):
        config = parse_config({"port": {"target": "rust"}})
        assert config.target == "rust"

    def test_oracle_cases(self):
        data = {
            "oracle": {
                "cases": [
                    {"name": "test1", "command": ["python", "main.py"]},
                    {"name": "test2", "command": "python main.py --flag"},
                ]
            }
        }
        config = parse_config(data)
        assert len(config.oracle_cases) == 2
        assert config.oracle_cases[0].name == "test1"
        assert config.oracle_cases[1].command == ["python", "main.py", "--flag"]

    def test_normalization(self):
        data = {
            "oracle": {
                "normalization": {
                    "strip_trailing_whitespace": False,
                    "sort_lines": True,
                }
            }
        }
        config = parse_config(data)
        assert config.normalization.strip_trailing_whitespace is False
        assert config.normalization.sort_lines is True

    def test_missing_command_raises(self):
        with pytest.raises(ValueError):
            parse_config({"oracle": {"cases": [{"name": "bad"}]}})

    def test_invalid_command_raises(self):
        with pytest.raises(ValueError):
            parse_config({"oracle": {"cases": [{"name": "bad", "command": []}]}})


class TestLoadConfig:
    def test_no_config_file(self, tmp_path):
        config = load_config(tmp_path)
        assert config is None

    def test_load_file(self, tmp_path):
        toml_content = """
[port]
target = "rust"

[[oracle.cases]]
name = "test"
command = ["python", "main.py"]
expected_exit = 0
"""
        (tmp_path / "pointer.toml").write_text(toml_content)
        config = load_config(tmp_path)
        assert config is not None
        assert config.target == "rust"
        assert len(config.oracle_cases) == 1
        assert config.oracle_cases[0].name == "test"


class TestAutoDiscover:
    def test_discovers_pyproject_scripts(self, tmp_path):
        pyproject = """
[project]
name = "myapp"
version = "0.1.0"

[project.scripts]
myapp = "myapp:main"
"""
        (tmp_path / "pyproject.toml").write_text(pyproject)
        cases = auto_discover_entry_points(tmp_path)
        assert len(cases) > 0
        assert any("myapp" in c.name for c in cases)

    def test_discovers_main_py(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        cases = auto_discover_entry_points(tmp_path)
        assert any("main" in c.name for c in cases)

    def test_skips_tests(self, tmp_path):
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_main.py").write_text("# test")
        (tmp_path / "main.py").write_text("print('hello')")
        cases = auto_discover_entry_points(tmp_path)
        # Should find main.py but skip test files
        assert any("main" in c.name for c in cases)
        assert not any("test" in c.name.lower() for c in cases)
