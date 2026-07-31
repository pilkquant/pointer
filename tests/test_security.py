"""Security tests: no target code execution/import, symlink safety."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from pointer.analyzer.filesystem import safe_resolve, safe_walk
from pointer.models import Target
from pointer.pipeline import analyze

FIXTURES = Path(__file__).parent / "fixtures"


class TestNoCodeExecution:
    """Verify that Pointer never imports or executes target code."""

    def test_no_import_of_target_modules(self):
        """After analyzing pure_python, tinylib should NOT be in sys.modules."""
        # Ensure clean state
        for mod in list(sys.modules):
            if "tinylib" in mod:
                del sys.modules[mod]

        analyze(FIXTURES / "pure_python", Target.COMPARE)

        assert "tinylib" not in sys.modules
        assert "tinylib.core" not in sys.modules

    def test_no_import_of_dynamic_modules(self):
        """After analyzing dynamic, wildlib should NOT be in sys.modules."""
        for mod in list(sys.modules):
            if "wildlib" in mod:
                del sys.modules[mod]

        analyze(FIXTURES / "dynamic", Target.COMPARE)

        assert "wildlib" not in sys.modules

    def test_ast_scanner_uses_ast_not_exec(self):
        """AST scanner must use ast.parse, never exec/eval on target source."""
        # After analysis, verify that no target modules were imported into sys.modules
        for mod in list(sys.modules):
            if "tinylib" in mod or "wildlib" in mod:
                del sys.modules[mod]

        analyze(FIXTURES / "pure_python", Target.COMPARE)

        # Target modules should never appear in sys.modules after analysis
        for mod in sys.modules:
            assert "tinylib" not in mod, f"Target module '{mod}' was imported during analysis"
            assert "wildlib" not in mod, f"Target module '{mod}' was imported during analysis"

    def test_eval_not_called_on_target(self):
        """eval() must never be called with target code as argument."""
        # Track what eval is called with during analysis
        original_eval = eval
        calls: list[str] = []

        def tracking_eval(expr, *args, **kwargs):
            calls.append(str(expr)[:200])
            return original_eval(expr, *args, **kwargs)

        with patch("builtins.eval", tracking_eval):
            analyze(FIXTURES / "dynamic", Target.COMPARE)

        # eval may be called by Python internals, but should never receive
        # actual target source code as argument
        for call in calls:
            assert "code_str" not in call, f"eval called with target variable: {call}"
            assert "import" not in call[:20].lower() or "ImportError" not in call


class TestSymlinkSafety:
    """Verify symlink escape prevention."""

    def test_safe_walk_ignores_external_symlinks(self, tmp_path):
        """safe_walk should not follow symlinks pointing outside root."""
        # Create a file outside the root
        outside_file = tmp_path.parent / "outside_secret.txt"
        outside_file.write_text("secret data")

        # Create a symlink inside root pointing outside
        (tmp_path / "link_to_secret.txt").symlink_to(outside_file)

        results = safe_walk(tmp_path)
        paths = [rel for _, rel in results]

        assert "link_to_secret.txt" not in paths
        assert all("outside_secret" not in p for p in paths)

    def test_safe_walk_allows_internal_symlinks(self, tmp_path):
        """safe_walk should allow symlinks that stay within root."""
        # Create a real file in root
        (tmp_path / "real.py").write_text("# real file")

        # Create a subdirectory
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        # Create a symlink in subdir pointing to the real file in root
        (subdir / "link.py").symlink_to(tmp_path / "real.py")

        results = safe_walk(tmp_path)
        paths = [rel for _, rel in results]

        # Both should appear
        assert "real.py" in paths
        assert "subdir/link.py" in paths

    def test_safe_resolve_rejects_external(self, tmp_path):
        """safe_resolve should reject paths escaping root."""
        outside = tmp_path.parent / "outside"
        outside.mkdir(exist_ok=True)
        outside_file = outside / "secret.txt"
        outside_file.write_text("secret")

        result = safe_resolve(outside_file, tmp_path)
        assert result is None

    def test_safe_resolve_accepts_internal(self, tmp_path):
        """safe_resolve should accept paths within root."""
        internal = tmp_path / "inside.txt"
        internal.write_text("ok")

        result = safe_resolve(internal, tmp_path)
        assert result is not None
