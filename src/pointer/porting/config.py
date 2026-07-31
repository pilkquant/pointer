"""Port configuration — pointer.toml parsing and oracle case definitions.

A ``pointer.toml`` in the source repository root declares the executable oracle
specification. It tells Pointer how to run the Python source as a deterministic
oracle and what behavior to compare the generated Rust against.

Example pointer.toml:

    [port]
    target = "rust"

    [[oracle.cases]]
    name = "basic"
    command = ["python", "-m", "tinycalc", "1 + 2"]
    expected_exit = 0

    [[oracle.cases]]
    name = "stdin"
    command = ["python", "-m", "tinycalc"]
    stdin = "3 * 4\\n"
    expected_exit = 0

    [[oracle.cases]]
    name = "error_path"
    command = ["python", "-m", "tinycalc", "invalid"]
    expected_exit = 1

    [oracle.normalization]
    strip_trailing_whitespace = true
    normalize_newlines = true
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    tomllib = None  # type: ignore[assignment]


@dataclass
class NormalizationConfig:
    """Declarative output normalization rules."""

    strip_trailing_whitespace: bool = True
    normalize_newlines: bool = True
    strip_color_codes: bool = False
    sort_lines: bool = False

    def normalize(self, text: str) -> str:
        """Apply configured normalizations to text."""
        result = text
        if self.normalize_newlines:
            result = result.replace("\r\n", "\n").replace("\r", "\n")
        if self.strip_color_codes:
            # Strip ANSI escape sequences
            result = re.sub(r"\x1b\[[0-9;]*m", "", result)
        if self.strip_trailing_whitespace:
            result = "\n".join(line.rstrip() for line in result.split("\n"))
        if self.sort_lines:
            result = "\n".join(sorted(result.strip().split("\n")))
        return result


@dataclass
class OracleCase:
    """A single oracle test case.

    Defines a command to run, its expected exit code, and optional stdin.
    The command is run with ``cwd`` set to the source root (for Python oracle)
    or the output workspace (for Rust target).
    """

    name: str
    command: list[str]
    stdin: str | None = None
    expected_exit: int = 0
    expected_stdout: str | None = None  # if None, captured dynamically
    expected_stderr: str | None = None
    timeout: float = 30.0
    env_allowlist: list[str] = field(default_factory=list)

    @property
    def has_dynamic_expected(self) -> bool:
        """True if expected output must be captured from Python first."""
        return self.expected_stdout is None

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "name": self.name,
            "command": self.command,
            "stdin": self.stdin,
            "expected_exit": self.expected_exit,
            "expected_stdout": self.expected_stdout,
            "expected_stderr": self.expected_stderr,
            "timeout": self.timeout,
            "env_allowlist": self.env_allowlist,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OracleCase:
        """Deserialize from dict."""
        return cls(
            name=data["name"],
            command=data["command"],
            stdin=data.get("stdin"),
            expected_exit=data.get("expected_exit", 0),
            expected_stdout=data.get("expected_stdout"),
            expected_stderr=data.get("expected_stderr"),
            timeout=data.get("timeout", 30.0),
            env_allowlist=data.get("env_allowlist", []),
        )


@dataclass
class PortConfig:
    """Full porting configuration parsed from pointer.toml."""

    target: str = "rust"
    oracle_cases: list[OracleCase] = field(default_factory=list)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    source_config_path: str | None = None
    raw_toml: dict | None = None

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "target": self.target,
            "oracle_cases": [c.to_dict() for c in self.oracle_cases],
            "normalization": {
                "strip_trailing_whitespace": self.normalization.strip_trailing_whitespace,
                "normalize_newlines": self.normalization.normalize_newlines,
                "strip_color_codes": self.normalization.strip_color_codes,
                "sort_lines": self.normalization.sort_lines,
            },
            "source_config_path": self.source_config_path,
        }


def load_config(source_root: Path) -> PortConfig | None:
    """Load pointer.toml from the source repository root.

    Returns None if no pointer.toml exists.
    Raises ValueError on parse errors.
    """
    toml_path = source_root / "pointer.toml"
    if not toml_path.exists():
        return None

    if tomllib is None:
        raise RuntimeError("tomllib not available (requires Python 3.11+)")

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)

    return parse_config(data, str(toml_path))


def parse_config(data: dict, config_path: str | None = None) -> PortConfig:
    """Parse a pointer.toml dict into PortConfig.

    Raises ValueError for malformed configurations.
    """
    port_section = data.get("port", {})
    target = port_section.get("target", "rust")

    # Parse normalization
    norm_data = data.get("oracle", {}).get("normalization", {})
    normalization = NormalizationConfig(
        strip_trailing_whitespace=norm_data.get("strip_trailing_whitespace", True),
        normalize_newlines=norm_data.get("normalize_newlines", True),
        strip_color_codes=norm_data.get("strip_color_codes", False),
        sort_lines=norm_data.get("sort_lines", False),
    )

    # Parse oracle cases
    cases_data = data.get("oracle", {}).get("cases", [])
    oracle_cases: list[OracleCase] = []
    for i, case_data in enumerate(cases_data):
        name = case_data.get("name", f"case_{i}")
        command = case_data.get("command")
        if not command:
            raise ValueError(f"Oracle case '{name}' has no command")
        if isinstance(command, str):
            command = shlex.split(command)
        if not isinstance(command, list) or not command:
            raise ValueError(f"Oracle case '{name}' has invalid command")

        oracle_cases.append(
            OracleCase(
                name=name,
                command=command,
                stdin=case_data.get("stdin"),
                expected_exit=case_data.get("expected_exit", 0),
                expected_stdout=case_data.get("expected_stdout"),
                expected_stderr=case_data.get("expected_stderr"),
                timeout=case_data.get("timeout", 30.0),
                env_allowlist=case_data.get("env_allowlist", []),
            )
        )

    return PortConfig(
        target=target,
        oracle_cases=oracle_cases,
        normalization=normalization,
        source_config_path=config_path,
        raw_toml=data,
    )


def auto_discover_entry_points(
    source_root: Path,
) -> list[OracleCase]:
    """Best-effort auto-discovery of potential oracle commands.

    This does NOT verify anything — it merely suggests candidate commands.
    The user must confirm or provide explicit pointer.toml cases.
    """
    candidates: list[OracleCase] = []

    # Check for console_scripts in pyproject.toml
    pyproject = source_root / "pyproject.toml"
    if pyproject.exists() and tomllib:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        scripts = data.get("project", {}).get("scripts", {})
        for name in scripts:
            # Suggest running with --help
            candidates.append(
                OracleCase(
                    name=f"discover_{name}_help",
                    command=[name, "--help"],
                    expected_exit=0,
                    timeout=10.0,
                )
            )

    # Check for main.py or cli.py
    for pattern in ["main.py", "cli.py", "__main__.py"]:
        for found in source_root.rglob(pattern):
            rel = found.relative_to(source_root)
            # Skip test/fixtures
            if "test" in str(rel).lower() or "fixture" in str(rel).lower():
                continue
            candidates.append(
                OracleCase(
                    name=f"discover_{found.stem}",
                    command=["python", str(rel), "--help"],
                    expected_exit=0,
                    timeout=10.0,
                )
            )

    return candidates
