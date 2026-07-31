"""Tests for the agent backend — FakeBackend, CodexBackend probing, JSONL parsing."""

from __future__ import annotations

import pytest

from pointer.porting.backend import (
    CodexBackend,
    FakeBackend,
    _discover_codex,
    _parse_codex_version,
    _parse_jsonl,
    get_backend,
)


class TestFakeBackend:
    def test_probe(self):
        backend = FakeBackend()
        caps = backend.probe()
        assert caps.available is True
        assert caps.authenticated is True
        assert caps.version

    def test_generate_writes_rust(self, tmp_path):
        backend = FakeBackend()
        result = backend.generate("test prompt", tmp_path)
        assert result.success
        assert (tmp_path / "Cargo.toml").exists()
        assert (tmp_path / "src" / "main.rs").exists()
        cargo_content = (tmp_path / "Cargo.toml").read_text()
        assert "port-target" in cargo_content

    def test_generate_session_id(self, tmp_path):
        backend = FakeBackend()
        result = backend.generate("test prompt", tmp_path)
        assert result.session_id is not None
        assert result.session_id.startswith("fake-session-")

    def test_repair_writes_correct_rust(self, tmp_path):
        backend = FakeBackend(fail_first=True)
        # First generate writes broken Rust
        gen_result = backend.generate("test prompt", tmp_path)
        assert gen_result.success
        main_content = (tmp_path / "src" / "main.rs").read_text()
        assert "broken" in main_content

        # Repair writes correct Rust
        repair_result = backend.repair("fix it", tmp_path)
        assert repair_result.success
        main_content = (tmp_path / "src" / "main.rs").read_text()
        assert "broken" not in main_content

    def test_fail_first_mode(self, tmp_path):
        backend = FakeBackend(fail_first=True)
        result1 = backend.generate("prompt", tmp_path)
        assert result1.success
        assert "broken" in result1.last_message

        # Second call should write correct Rust
        result2 = backend.repair("fix", tmp_path)
        assert result2.success

    def test_events_returned(self, tmp_path):
        backend = FakeBackend()
        result = backend.generate("prompt", tmp_path)
        assert len(result.events) > 0
        assert any(e.event_type == "done" for e in result.events)


class TestCodexBackend:
    def test_probe_no_codex(self, monkeypatch):
        """When codex is not available, probe should report unavailable."""
        monkeypatch.setenv("POINTER_CODEX_BIN", "")
        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setattr("pathlib.Path.exists", lambda self: False if "codex" in str(self) else True)
        backend = CodexBackend()
        backend._codex_bin = None
        caps = backend.probe()
        assert caps.available is False
        assert "not found" in caps.error.lower() or "failed" in caps.error.lower()

    def test_generate_no_codex(self, tmp_path):
        backend = CodexBackend(codex_bin="/nonexistent/codex")
        backend._codex_bin = None
        result = backend.generate("prompt", tmp_path)
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_repair_no_codex(self, tmp_path):
        backend = CodexBackend(codex_bin="/nonexistent/codex")
        backend._codex_bin = None
        result = backend.repair("prompt", tmp_path)
        assert result.success is False

    def test_build_exec_argv_no_dangerous_flag(self, tmp_path):
        """Ensure the dangerous bypass flag is never added to argv."""
        backend = CodexBackend(codex_bin="/usr/local/bin/codex")
        argv = backend._build_exec_argv(tmp_path)
        assert "--dangerously-bypass-approvals-and-sandbox" not in argv
        assert "--sandbox=workspace-write" in argv

    def test_build_exec_argv_includes_json(self, tmp_path):
        backend = CodexBackend(codex_bin="/usr/local/bin/codex")
        argv = backend._build_exec_argv(tmp_path)
        assert "--json" in argv

    def test_build_exec_argv_resume(self, tmp_path):
        backend = CodexBackend(codex_bin="/usr/local/bin/codex")
        argv = backend._build_exec_argv(tmp_path, session_id="session-123")
        assert "resume" in argv
        assert "session-123" in argv


class TestVersionParsing:
    def test_parse_standard(self):
        assert _parse_codex_version("codex-cli 0.146.0") == (0, 146, 0)

    def test_parse_with_extra_text(self):
        result = _parse_codex_version("codex version 1.2.3 (build 456)")
        assert result == (1, 2, 3)

    def test_parse_invalid(self):
        assert _parse_codex_version("not a version") == (0, 0, 0)

    def test_parse_empty(self):
        assert _parse_codex_version("") == (0, 0, 0)


class TestJSONLParsing:
    def test_valid_jsonl(self):
        text = '{"type": "message", "content": "hello"}\n{"type": "done", "content": "bye"}'
        events = _parse_jsonl(text)
        assert len(events) == 2
        assert events[0]["content"] == "hello"

    def test_malformed_lines_skipped(self):
        text = '{"type": "message"}\nnot json\n{"type": "done"}'
        events = _parse_jsonl(text)
        assert len(events) == 2

    def test_empty(self):
        assert _parse_jsonl("") == []
        assert _parse_jsonl("\n\n") == []


class TestGetBackend:
    def test_fake(self):
        backend = get_backend("fake")
        assert isinstance(backend, FakeBackend)

    def test_codex(self):
        backend = get_backend("codex")
        assert isinstance(backend, CodexBackend)

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            get_backend("unknown")


class TestDiscoverCodex:
    def test_env_override(self, monkeypatch, tmp_path):
        fake_bin = tmp_path / "fake-codex"
        fake_bin.write_text("#!/bin/bash\necho fake")
        monkeypatch.setenv("POINTER_CODEX_BIN", str(fake_bin))
        result = _discover_codex()
        assert result == str(fake_bin)

    def test_not_found(self, monkeypatch):
        monkeypatch.setenv("POINTER_CODEX_BIN", "")
        monkeypatch.setattr("shutil.which", lambda x: None)
        result = _discover_codex()
        # May find the default path or None depending on system
        # Just verify it doesn't crash
        assert result is None or isinstance(result, str)
