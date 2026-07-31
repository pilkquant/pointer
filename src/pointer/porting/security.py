"""Security utilities for the porting engine.

Handles:
- Secret redaction in logs and reports
- Path confinement (prevent escapes outside allowed roots)
- Environment sanitization for subprocess execution
- Symlink protection
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Patterns for common secret formats (redacted from all output)
_SECRET_PATTERNS = [
    # API keys / tokens (various prefixes)
    re.compile(r"(?i)(sk-[a-zA-Z0-9]{20,})"),
    re.compile(r"(?i)(gho_[a-zA-Z0-9]{36})"),
    re.compile(r"(?i)(ghp_[a-zA-Z0-9]{36})"),
    re.compile(r"(?i)(github_pat_[a-zA-Z0-9_]{82})"),
    re.compile(r"(?i)(xox[baprs]-[a-zA-Z0-9-]{10,})"),
    re.compile(r"(?i)(AKIA[0-9A-Z]{16})"),
    re.compile(r"(?i)(AIza[0-9A-Za-z\-_]{35})"),
    # Generic key=value patterns for common secret names
    re.compile(
        r"(?i)((?:api[_-]?key|secret|token|password|passwd|pwd|credential|auth)"
        r"(?:\s*[=:]\s*)['\"]?)([^\s'\"]{8,})"
    ),
    # Bearer tokens
    re.compile(r"(?i)(bearer\s+)([a-zA-Z0-9\-._~+/]+=*)"),
    # JWT
    re.compile(r"(eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})"),
]

_REDACTED = "[REDACTED]"

# Environment variable names that look like secrets
_SECRET_ENV_NAMES = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CODEX_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GIT_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "DATABASE_URL",
    "DB_PASSWORD",
    "SECRET_KEY",
    "API_KEY",
    "API_SECRET",
    "STRIPE_SECRET_KEY",
    "STRIPE_API_KEY",
}

# Environment variable names that may contain paths useful to Codex
_PATH_ENV_NAMES = {
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "SHELL",
    "TMPDIR",
    "TMP",
    "TEMP",
    "RUSTUP_HOME",
    "CARGO_HOME",
    "POINTER_CODEX_BIN",
}


def redact_secrets(text: str) -> str:
    """Redact likely secrets from a text string.

    Returns a copy with secrets replaced by [REDACTED].
    """
    result = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups == 2:
            result = pattern.sub(lambda m: m.group(1) + _REDACTED, result)
        else:
            result = pattern.sub(_REDACTED, result)
    return result


def is_secret_env_name(name: str) -> bool:
    """Check if an environment variable name looks like a secret."""
    upper = name.upper()
    if upper in _SECRET_ENV_NAMES:
        return True
    # Heuristic: names containing common secret keywords
    for keyword in ("SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL", "API_KEY"):
        if keyword in upper:
            return True
    return False


def sanitize_env(
    base_env: dict[str, str],
    *,
    allowlist: list[str] | None = None,
    extra_allowlist: list[str] | None = None,
) -> dict[str, str]:
    """Build a sanitized environment for subprocess execution.

    Starts with a minimal allowlist of safe env vars (PATH, HOME, etc.),
    adds any extra allowed vars, and strips anything that looks like a secret.

    Args:
        base_env: The source environment (usually os.environ).
        allowlist: Override the default allowlist entirely.
        extra_allowlist: Additional env var names to include.
    """
    allowed = set(allowlist) if allowlist is not None else set(_PATH_ENV_NAMES)
    if extra_allowlist:
        allowed.update(extra_allowlist)

    result: dict[str, str] = {}
    for name in sorted(allowed):
        if name in base_env and not is_secret_env_name(name):
            result[name] = base_env[name]

    return result


def validate_path_confined(
    path: Path,
    allowed_roots: list[Path],
    *,
    follow_symlinks: bool = True,
) -> Path:
    """Validate that a path is confined within one of the allowed roots.

    Resolves symlinks to prevent escapes. Raises ValueError if the path
    escapes all allowed roots.

    Returns the resolved path.
    """
    if follow_symlinks:
        try:
            resolved = path.resolve(strict=False)
        except (OSError, RuntimeError):
            resolved = path.absolute()
    else:
        resolved = path.absolute()

    for root in allowed_roots:
        try:
            root_resolved = root.resolve(strict=False)
        except (OSError, RuntimeError):
            root_resolved = root.absolute()

        try:
            resolved.relative_to(root_resolved)
            return resolved
        except ValueError:
            continue

    raise ValueError(
        f"Path '{path}' resolves to '{resolved}' which is outside all allowed roots: {[str(r) for r in allowed_roots]}"
    )


def check_symlink_escape(
    path: Path,
    allowed_roots: list[Path],
) -> bool:
    """Check if a path is a symlink that escapes allowed roots.

    Returns True if the symlink target is outside all allowed roots.
    """
    if not path.is_symlink():
        return False

    target = path.resolve(strict=False)
    for root in allowed_roots:
        root_resolved = root.resolve(strict=False)
        try:
            target.relative_to(root_resolved)
            return False  # Inside this root, OK
        except ValueError:
            continue
    return True  # Escapes all roots


def safe_walk(
    root: Path,
    allowed_roots: list[Path],
) -> list[Path]:
    """Walk a directory tree, skipping symlinks that escape allowed roots.

    Returns a list of files that are safe to read/process.
    """
    safe_files: list[Path] = []
    allowed_resolved = [r.resolve(strict=False) for r in allowed_roots]

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dir_path = Path(dirpath)

        # Filter out symlinked directories that escape
        safe_dirs: list[str] = []
        for dname in dirnames:
            dpath = dir_path / dname
            if dpath.is_symlink():
                if check_symlink_escape(dpath, allowed_resolved):
                    continue  # Skip escaping symlinks
            safe_dirs.append(dname)
        dirnames[:] = safe_dirs  # Modify in-place to prune walk

        for fname in filenames:
            fpath = dir_path / fname
            if fpath.is_symlink():
                if check_symlink_escape(fpath, allowed_resolved):
                    continue
            safe_files.append(fpath)

    return safe_files


def truncate_output(text: str, max_chars: int = 50000) -> str:
    """Truncate output to a maximum character count.

    Appends a truncation notice if truncated.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n... [truncated: {len(text) - max_chars} more characters omitted]"


def assert_no_dangerous_flag(argv: list[str]) -> None:
    """Assert that a command argv does not contain dangerous flags.

    Raises ValueError if a dangerous flag is found.
    """
    dangerous = "--dangerously-bypass-approvals-and-sandbox"
    joined = " ".join(argv)
    if dangerous in joined:
        raise ValueError(f"Refusing to execute command with dangerous flag: {dangerous}")

    # Also block shell=True patterns
    if any(part == "shell=True" for part in argv):
        raise ValueError("Refusing to use shell=True in subprocess")


def require_consent(
    *,
    has_consent: bool,
    auto_yes: bool,
    prompt_fn=None,
) -> bool:
    """Check or request consent for a security-sensitive operation.

    Args:
        has_consent: Whether consent was already given (--allow-source-execution).
        auto_yes: Whether --yes was passed (auto-confirm non-interactive).
        prompt_fn: Optional callable for interactive prompt. If None and
            consent is needed, returns False.

    Returns True if consent is given, False otherwise.
    """
    if has_consent:
        return True
    if auto_yes:
        # --yes does NOT grant source execution consent by itself
        # Source execution always needs explicit --allow-source-execution
        return False
    if prompt_fn is not None:
        return bool(prompt_fn())
    return False
