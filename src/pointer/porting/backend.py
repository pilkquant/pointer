"""Agent backend protocol — replaceable LLM agent interface.

Defines a stable protocol independent of Codex, plus two implementations:

- ``CodexBackend``: invokes the real OpenAI Codex CLI.
- ``FakeBackend``: deterministic backend for tests and CI without network.

Both conform to ``AgentBackend`` so the runner is agent-agnostic.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .security import assert_no_dangerous_flag, redact_secrets, truncate_output


@dataclass
class BackendCapabilities:
    """Probed capabilities of an agent backend."""

    available: bool = False
    version: str = ""
    authenticated: bool = False
    error: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentEvent:
    """A single structured event from the agent."""

    event_type: str  # "message", "tool_call", "error", "done", "meta"
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Result of an agent generation or repair invocation."""

    success: bool
    session_id: str | None = None
    thread_id: str | None = None
    events: list[AgentEvent] = field(default_factory=list)
    raw_output: str = ""
    last_message: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    exit_code: int | None = None


class AgentBackend(Protocol):
    """Protocol for replaceable agent backends."""

    def probe(self) -> BackendCapabilities:
        """Probe capabilities: availability, version, authentication."""
        ...

    def generate(
        self,
        prompt: str,
        workspace: Path,
        *,
        timeout: float = 600.0,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Initial generation: ask the agent to create a Rust workspace."""
        ...

    def repair(
        self,
        prompt: str,
        workspace: Path,
        *,
        session_id: str | None = None,
        timeout: float = 600.0,
    ) -> AgentResult:
        """Repair: ask the agent to fix issues using resume or a new turn."""
        ...


# ---------------------------------------------------------------------------
# FakeBackend — deterministic, no network/auth
# ---------------------------------------------------------------------------

# A minimal but real Rust workspace that implements a calculator CLI.
# Used by FakeBackend for tests and CI.
_FAKE_RUST_MAIN = r"""use std::env;
use std::io::{self, BufRead, Write};
use std::process;

fn parse_and_eval(input: &str) -> Result<f64, String> {
    let input = input.trim();
    if input.is_empty() {
        return Err("empty input".to_string());
    }

    // Tokenize: numbers and operators
    let mut tokens: Vec<String> = Vec::new();
    let mut current = String::new();
    for ch in input.chars() {
        if ch.is_whitespace() {
            if !current.is_empty() {
                tokens.push(current.clone());
                current.clear();
            }
            continue;
        }
        if ch == '+' || ch == '-' || ch == '*' || ch == '/' {
            if !current.is_empty() {
                tokens.push(current.clone());
                current.clear();
            }
            tokens.push(ch.to_string());
        } else if ch.is_ascii_digit() || ch == '.' {
            current.push(ch);
        } else {
            return Err(format!("unexpected character: {}", ch));
        }
    }
    if !current.is_empty() {
        tokens.push(current);
    }

    if tokens.is_empty() {
        return Err("no tokens".to_string());
    }

    // Simple left-to-right evaluation with operator precedence (* / before + -)
    // First pass: handle * and /
    let mut values: Vec<f64> = Vec::new();
    let mut ops: Vec<char> = Vec::new();

    let mut expect_value = true;
    for tok in &tokens {
        if expect_value {
            match tok.parse::<f64>() {
                Ok(v) => values.push(v),
                Err(_) => return Err(format!("invalid number: {}", tok)),
            }
            expect_value = false;
        } else {
            match tok.chars().next() {
                Some(c @ ('+' | '-' | '*' | '/')) => ops.push(c),
                _ => return Err(format!("expected operator, got: {}", tok)),
            }
            expect_value = true;
        }
    }

    if expect_value {
        return Err("expression ends with operator".to_string());
    }

    // First pass: * and /
    let mut i = 0;
    while i < ops.len() {
        if ops[i] == '*' || ops[i] == '/' {
            let left = values[i];
            let right = values[i + 1];
            let result = if ops[i] == '*' {
                left * right
            } else {
                if right == 0.0 {
                    return Err("division by zero".to_string());
                }
                left / right
            };
            values[i] = result;
            values.remove(i + 1);
            ops.remove(i);
        } else {
            i += 1;
        }
    }

    // Second pass: + and -
    let mut result = values[0];
    for (j, op) in ops.iter().enumerate() {
        let right = values[j + 1];
        result = match op {
            '+' => result + right,
            '-' => result - right,
            _ => unreachable!(),
        };
    }

    // Format: integers without decimal if whole
    if result == result.floor() && result.is_finite() {
        Ok(result as i64 as f64)
    } else {
        Ok(result)
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() < 2 {
        // Read from stdin
        let stdin = io::stdin();
        let stdout = io::stdout();
        let mut stdout = stdout.lock();
        for line in stdin.lock().lines() {
            match line {
                Ok(l) => {
                    if l.trim().is_empty() {
                        continue;
                    }
                    match parse_and_eval(&l) {
                        Ok(v) => {
                            if v == v.floor() && v.is_finite() {
                                let _ = writeln!(stdout, "{}", v as i64);
                            } else {
                                let _ = writeln!(stdout, "{}", v);
                            }
                        }
                        Err(e) => {
                            let _ = writeln!(stdout, "Error: {}", e);
                            process::exit(1);
                        }
                    }
                }
                Err(_) => break,
            }
        }
        return;
    }

    // Join all args as a single expression
    let expr = args[1..].join(" ");
    match parse_and_eval(&expr) {
        Ok(v) => {
            if v == v.floor() && v.is_finite() {
                println!("{}", v as i64);
            } else {
                println!("{}", v);
            }
        }
        Err(e) => {
            println!("Error: {}", e);
            process::exit(1);
        }
    }
}
"""

_FAKE_CARGO_TOML = """[package]
name = "port-target"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "port-target"
path = "src/main.rs"

[dependencies]
"""


class FakeBackend:
    """Deterministic fake agent backend for tests and CI.

    Writes a real, compilable Rust calculator to the workspace.
    This allows testing the full pipeline (build, verify) without network.
    """

    BACKEND_NAME = "fake"
    VERSION = "fake-1.0.0"

    def __init__(self, *, rust_content: str | None = None, fail_first: bool = False):
        """Initialize the fake backend.

        Args:
            rust_content: Custom Rust source to write (default: calculator).
            fail_first: If True, write broken Rust on first generate, then
                        require a repair to write correct Rust.
        """
        self._rust_content = rust_content or _FAKE_RUST_MAIN
        self._fail_first = fail_first
        self._call_count = 0

    def probe(self) -> BackendCapabilities:
        """Always available."""
        return BackendCapabilities(
            available=True,
            version=self.VERSION,
            authenticated=True,
        )

    def _write_workspace(self, workspace: Path, broken: bool = False) -> None:
        """Write the Rust workspace."""
        src_dir = workspace / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        if broken:
            # Write intentionally broken Rust for repair testing
            (src_dir / "main.rs").write_text("fn main() { broken syntax!!! }\n", encoding="utf-8")
        else:
            (src_dir / "main.rs").write_text(self._rust_content, encoding="utf-8")

        (workspace / "Cargo.toml").write_text(_FAKE_CARGO_TOML, encoding="utf-8")

    def generate(
        self,
        prompt: str,
        workspace: Path,
        *,
        timeout: float = 600.0,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Generate a Rust workspace deterministically."""
        start = time.monotonic()
        self._call_count += 1

        broken = self._fail_first and self._call_count == 1
        self._write_workspace(workspace, broken=broken)

        session_id = f"fake-session-{self._call_count}"
        return AgentResult(
            success=True,
            session_id=session_id,
            events=[
                AgentEvent(event_type="meta", content=f"Generated Rust workspace at {workspace}"),
                AgentEvent(event_type="done", content="Generation complete"),
            ],
            raw_output=f"[fake] wrote Rust workspace to {workspace}\n",
            last_message=f"Generated {'broken' if broken else 'working'} Rust workspace",
            duration_seconds=time.monotonic() - start,
        )

    def repair(
        self,
        prompt: str,
        workspace: Path,
        *,
        session_id: str | None = None,
        timeout: float = 600.0,
    ) -> AgentResult:
        """Repair by writing the correct Rust."""
        start = time.monotonic()
        self._call_count += 1

        self._write_workspace(workspace, broken=False)

        return AgentResult(
            success=True,
            session_id=session_id or f"fake-repair-{self._call_count}",
            events=[
                AgentEvent(event_type="meta", content=f"Repaired Rust workspace at {workspace}"),
                AgentEvent(event_type="done", content="Repair complete"),
            ],
            raw_output=f"[fake] repaired Rust workspace at {workspace}\n",
            last_message="Repaired: wrote correct Rust workspace",
            duration_seconds=time.monotonic() - start,
        )


# ---------------------------------------------------------------------------
# CodexBackend — real OpenAI Codex CLI
# ---------------------------------------------------------------------------

_CODEX_VERSION_MIN = (0, 1, 0)  # Minimum supported version


def _discover_codex() -> str | None:
    """Discover the Codex CLI binary.

    Checks POINTER_CODEX_BIN, then PATH.
    """
    # 1. Explicit override
    override = os.environ.get("POINTER_CODEX_BIN")
    if override and Path(override).exists():
        return override

    # 2. Default location (task-specified)
    default_path = Path.home() / ".local" / "bin" / "codex"
    if default_path.exists():
        return str(default_path)

    # 3. PATH lookup
    return shutil.which("codex")


def _parse_codex_version(version_str: str) -> tuple[int, ...]:
    """Parse 'codex-cli 0.146.0' into (0, 146, 0)."""
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_str)
    if not match:
        return (0, 0, 0)
    return tuple(int(x) for x in match.groups())


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill a process and its entire process group."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


def _parse_jsonl(text: str) -> list[dict[str, Any]]:
    """Parse JSONL output defensively.

    Returns a list of parsed JSON objects. Malformed lines are skipped.
    """
    events: list[dict[str, Any]] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # Skip malformed lines
    return events


class CodexBackend:
    """Real OpenAI Codex CLI backend.

    Invokes ``codex exec`` with JSONL output inside an isolated workspace.
    """

    BACKEND_NAME = "codex"

    def __init__(self, *, codex_bin: str | None = None):
        """Initialize, optionally overriding the Codex binary path."""
        self._codex_bin = codex_bin or _discover_codex()

    def probe(self) -> BackendCapabilities:
        """Probe Codex CLI availability, version, and auth."""
        if not self._codex_bin:
            return BackendCapabilities(
                available=False,
                error="Codex CLI not found. Set POINTER_CODEX_BIN or install codex.",
            )

        # Check version
        try:
            version_result = subprocess.run(
                [self._codex_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            version_str = version_result.stdout.strip()
            version_tuple = _parse_codex_version(version_str)

            if version_tuple < _CODEX_VERSION_MIN:
                return BackendCapabilities(
                    available=False,
                    version=version_str,
                    error=f"Codex version {version_str} is below minimum {'.'.join(map(str, _CODEX_VERSION_MIN))}",
                )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            return BackendCapabilities(
                available=False,
                error=f"Failed to probe Codex version: {e}",
            )

        # Check auth
        try:
            auth_result = subprocess.run(
                [self._codex_bin, "login", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            auth_output = auth_result.stdout + auth_result.stderr
            authenticated = "logged in" in auth_output.lower() and "not logged in" not in auth_output.lower()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            authenticated = False

        return BackendCapabilities(
            available=True,
            version=version_str,
            authenticated=authenticated,
            details={"codex_bin": self._codex_bin},
        )

    def _build_exec_argv(
        self,
        prompt: str,
        workspace: Path,
        *,
        sandbox: str = "workspace-write",
        session_id: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> list[str]:
        """Build the codex exec argv array.

        Never uses shell=True. Never uses dangerous bypass flag.
        """
        assert_no_dangerous_flag([prompt])  # Validate prompt doesn't contain dangerous flags

        argv = [
            self._codex_bin,
            "exec",
            "--json",
            f"--sandbox={sandbox}",
            "-C",
            str(workspace),
        ]

        if session_id:
            argv.extend(["resume", session_id])

        argv.append(prompt)

        # Validate no dangerous flag leaked in
        assert_no_dangerous_flag(argv)
        return argv

    def _run_codex(
        self,
        argv: list[str],
        workspace: Path,
        timeout: float,
    ) -> AgentResult:
        """Execute a codex command and parse results."""
        start = time.monotonic()

        # Build sanitized environment
        from .security import sanitize_env

        clean_env = sanitize_env(dict(os.environ))

        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(workspace),
                env=clean_env,
                preexec_fn=os.setsid,  # New process group for clean kill
            )
        except FileNotFoundError as e:
            return AgentResult(
                success=False,
                error=f"Codex binary not found: {e}",
                duration_seconds=time.monotonic() - start,
            )

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_group(proc)
            return AgentResult(
                success=False,
                error=f"Codex timed out after {timeout}s",
                duration_seconds=time.monotonic() - start,
                exit_code=-1,
            )

        duration = time.monotonic() - start
        raw_output = truncate_output(stdout.decode("utf-8", errors="replace"), 50000)
        raw_stderr = truncate_output(stderr.decode("utf-8", errors="replace"), 20000)

        # Redact secrets from all output
        raw_output = redact_secrets(raw_output)
        raw_stderr = redact_secrets(raw_stderr)

        # Parse JSONL events
        events_data = _parse_jsonl(raw_output)
        events: list[AgentEvent] = []
        session_id: str | None = None
        thread_id: str | None = None
        last_message = ""

        for evt in events_data:
            evt_type = evt.get("type", evt.get("event", "message"))
            content = evt.get("content", evt.get("message", evt.get("text", "")))

            # Extract session/thread IDs
            if "session_id" in evt:
                session_id = evt["session_id"]
            if "thread_id" in evt:
                thread_id = evt["thread_id"]

            if evt_type in ("message", "assistant", "completed"):
                if content and not last_message:
                    last_message = content
                if content:
                    events.append(
                        AgentEvent(
                            event_type="message",
                            content=redact_secrets(str(content)),
                            metadata=evt,
                        )
                    )
            elif evt_type == "error":
                events.append(
                    AgentEvent(
                        event_type="error",
                        content=redact_secrets(str(content)),
                        metadata=evt,
                    )
                )
            else:
                events.append(
                    AgentEvent(
                        event_type=evt_type,
                        content=redact_secrets(str(content)),
                        metadata=evt,
                    )
                )

        success = proc.returncode == 0

        # If we have structured events, the last "done"/"completed" message is the real last_message
        for evt in reversed(events_data):
            msg = evt.get("last_message") or evt.get("content") or evt.get("message", "")
            if msg:
                last_message = redact_secrets(str(msg))
                break

        error = ""
        if not success:
            error = f"Codex exited with code {proc.returncode}"
            if raw_stderr:
                error += f": {raw_stderr[:500]}"
        elif not last_message:
            last_message = "(no output from Codex)"

        return AgentResult(
            success=success,
            session_id=session_id,
            thread_id=thread_id,
            events=events,
            raw_output=raw_output,
            last_message=last_message,
            error=error,
            duration_seconds=duration,
            exit_code=proc.returncode,
        )

    def generate(
        self,
        prompt: str,
        workspace: Path,
        *,
        timeout: float = 600.0,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Generate a Rust workspace using real Codex."""
        if not self._codex_bin:
            return AgentResult(
                success=False,
                error="Codex CLI not found. Set POINTER_CODEX_BIN or install codex.",
            )

        argv = self._build_exec_argv(prompt, workspace, sandbox="workspace-write", output_schema=output_schema)
        return self._run_codex(argv, workspace, timeout)

    def repair(
        self,
        prompt: str,
        workspace: Path,
        *,
        session_id: str | None = None,
        timeout: float = 600.0,
    ) -> AgentResult:
        """Repair using Codex resume when possible."""
        if not self._codex_bin:
            return AgentResult(
                success=False,
                error="Codex CLI not found.",
            )

        argv = self._build_exec_argv(prompt, workspace, sandbox="workspace-write", session_id=session_id)
        return self._run_codex(argv, workspace, timeout)


def get_backend(name: str, **kwargs: Any) -> AgentBackend:
    """Factory: get a backend by name.

    Args:
        name: "codex" for CodexBackend, "fake" for FakeBackend.
    """
    if name == "codex":
        return CodexBackend(**kwargs)
    elif name == "fake":
        return FakeBackend(**kwargs)
    else:
        raise ValueError(f"Unknown backend: {name}")
