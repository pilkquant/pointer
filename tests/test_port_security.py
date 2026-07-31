"""Tests for security utilities — redaction, path confinement, consent, dangerous flags."""

from __future__ import annotations

import os

import pytest

from pointer.porting.security import (
    assert_no_dangerous_flag,
    check_symlink_escape,
    is_secret_env_name,
    redact_secrets,
    require_consent,
    safe_walk,
    sanitize_env,
    truncate_output,
    validate_path_confined,
)


class TestRedactSecrets:
    def test_openai_key(self):
        text = "sk-abcd1234567890efghij"
        assert redact_secrets(text) == "[REDACTED]"

    def test_github_token(self):
        text = "gho_" + "a" * 36
        assert "[REDACTED]" in redact_secrets(text)

    def test_generic_api_key(self):
        text = "api_key=supersecret12345678"
        redacted = redact_secrets(text)
        assert "supersecret12345678" not in redacted
        assert "[REDACTED]" in redacted

    def test_bearer_token(self):
        text = "Bearer dGhpcyBpcyBhIHRlc3QgdG9rZW4"
        redacted = redact_secrets(text)
        assert "dGhpcyBpcyBhIHRlc3QgdG9rZW4" not in redacted

    def test_no_false_positive(self):
        text = "Hello world this is normal text"
        assert redact_secrets(text) == text

    def test_jwt(self):
        # Fake JWT structure
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        redacted = redact_secrets(jwt)
        assert "[REDACTED]" in redacted

    def test_password_in_url(self):
        text = "password=mySecretPassword123"
        redacted = redact_secrets(text)
        assert "mySecretPassword123" not in redacted

    def test_preserves_non_secret_content(self):
        text = "The answer is 42 and api_key=secretkey123"
        redacted = redact_secrets(text)
        assert "The answer is 42" in redacted
        assert "secretkey123" not in redacted


class TestSecretEnvNames:
    def test_known_secret_names(self):
        assert is_secret_env_name("OPENAI_API_KEY")
        assert is_secret_env_name("GITHUB_TOKEN")
        assert is_secret_env_name("DATABASE_PASSWORD")

    def test_heuristic_names(self):
        assert is_secret_env_name("MY_API_SECRET")
        assert is_secret_env_name("CUSTOM_TOKEN")
        assert is_secret_env_name("DB_PASSWORD")

    def test_non_secret_names(self):
        assert not is_secret_env_name("PATH")
        assert not is_secret_env_name("HOME")
        assert not is_secret_env_name("USER")


class TestSanitizeEnv:
    def test_removes_secrets(self):
        env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "OPENAI_API_KEY": "sk-secret",
            "GITHUB_TOKEN": "gho_secret",
            "MY_CUSTOM_TOKEN": "secret",
        }
        clean = sanitize_env(env)
        assert "PATH" in clean
        assert "HOME" in clean
        assert "OPENAI_API_KEY" not in clean
        assert "GITHUB_TOKEN" not in clean
        assert "MY_CUSTOM_TOKEN" not in clean

    def test_extra_allowlist(self):
        env = {"PATH": "/usr/bin", "MY_VAR": "value"}
        clean = sanitize_env(env, extra_allowlist=["MY_VAR"])
        assert "MY_VAR" in clean

    def test_custom_allowlist(self):
        env = {"PATH": "/usr/bin", "HOME": "/h", "CUSTOM": "value"}
        clean = sanitize_env(env, allowlist=["PATH"])
        assert "PATH" in clean
        assert "HOME" not in clean


class TestPathConfined:
    def test_inside_root(self, tmp_path):
        path = tmp_path / "subdir" / "file.txt"
        path.parent.mkdir(parents=True)
        path.write_text("test")
        result = validate_path_confined(path, [tmp_path])
        assert result == path.resolve()

    def test_outside_root_raises(self, tmp_path):
        outside = tmp_path.parent.parent
        with pytest.raises(ValueError):
            validate_path_confined(outside, [tmp_path])

    def test_multiple_roots(self, tmp_path):
        root1 = tmp_path / "root1"
        root2 = tmp_path / "root2"
        root1.mkdir()
        root2.mkdir()
        path = root2 / "file.txt"
        path.write_text("test")
        result = validate_path_confined(path, [root1, root2])
        assert result == path.resolve()


class TestSymlinkEscape:
    def test_normal_file(self, tmp_path):
        path = tmp_path / "file.txt"
        path.write_text("test")
        assert not check_symlink_escape(path, [tmp_path])

    def test_safe_symlink(self, tmp_path):
        target = tmp_path / "target.txt"
        target.write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        assert not check_symlink_escape(link, [tmp_path])

    @pytest.mark.skipif(os.name == "nt", reason="symlinks not reliable on Windows")
    def test_escaping_symlink(self, tmp_path):
        outside = tmp_path.parent / "outside.txt"
        try:
            outside.write_text("outside")
        except (OSError, PermissionError):
            pytest.skip("Cannot create file outside tmp_path")
        link = tmp_path / "escape.txt"
        try:
            link.symlink_to(outside)
        except (OSError, PermissionError):
            pytest.skip("Cannot create symlink")
        assert check_symlink_escape(link, [tmp_path])


class TestSafeWalk:
    def test_walk_no_symlinks(self, tmp_path):
        (tmp_path / "dir1").mkdir()
        (tmp_path / "dir1" / "file1.py").write_text("# file 1")
        (tmp_path / "file2.py").write_text("# file 2")
        files = safe_walk(tmp_path, [tmp_path])
        paths = [str(f) for f in files]
        assert any("file1.py" in p for p in paths)
        assert any("file2.py" in p for p in paths)


class TestConsent:
    def test_has_consent(self):
        assert require_consent(has_consent=True, auto_yes=False) is True

    def test_no_consent_no_auto_yes(self):
        assert require_consent(has_consent=False, auto_yes=False) is False

    def test_auto_yes_does_not_grant_execution(self):
        assert require_consent(has_consent=False, auto_yes=True) is False

    def test_prompt_fn(self):
        assert require_consent(has_consent=False, auto_yes=False, prompt_fn=lambda: True) is True


class TestTruncateOutput:
    def test_short_text(self):
        assert truncate_output("hello", 100) == "hello"

    def test_long_text(self):
        text = "x" * 200
        result = truncate_output(text, 100)
        assert len(result) > 100  # includes truncation notice
        assert "truncated" in result


class TestDangerousFlag:
    def test_blocks_dangerous_flag(self):
        with pytest.raises(ValueError):
            assert_no_dangerous_flag(["codex", "exec", "--dangerously-bypass-approvals-and-sandbox"])

    def test_allows_safe_flags(self):
        assert_no_dangerous_flag(["codex", "exec", "--json", "--sandbox=workspace-write"])

    def test_blocks_shell_true(self):
        with pytest.raises(ValueError):
            assert_no_dangerous_flag(["shell=True"])
