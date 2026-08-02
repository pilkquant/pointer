# Pointer

**Point it at Python. Get an evidence-backed path to native.**

Pointer is a static portability-analysis CLI **and** Codex-backed Python→Rust porting workflow. v0.1 analyzes any Python repository and produces evidence-backed portability reports. v0.2 adds one-command porting: `pointer port ./my-project --target rust --agent codex`.

**Current release: v0.2.1.** This maintenance release improves Rust toolchain discovery and makes failed/repairing port runs more reliable and diagnosable.

## What's new in v0.2.0 — The Final Fantasy

```bash
pointer port ./python-repo --target rust --agent codex
```

One command initiates: analysis → oracle capture → plan → Codex generation → Rust build/test → behavioral comparison → bounded repair → evidence report. The command either returns a **verified** native result or fails honestly with exact blockers and resumable state.

Key additions:

- **Durable run state machine** — every run is persisted under `.pointer/runs/<run-id>/` with atomic state writes. Interrupted runs resume without repeating completed work.
- **Replaceable agent backend** — `AgentBackend` protocol with `CodexBackend` (real CLI) and `FakeBackend` (deterministic, no network). CI uses the fake backend — no model spending required.
- **Executable oracle** — `pointer.toml` defines deterministic test cases. Python outputs are captured *before* generation, then compared against Rust outputs after build.
- **Differential verification** — every oracle case (exit code, stdout, stderr) is compared after the Rust port builds. No false `verified` verdicts.
- **Bounded repair** — on build/test/behavior failure, structured diagnostics are fed back to Codex via resume. Default budget: 3 attempts. Never loops forever.
- **Evidence reports** — every run produces `report.md` and `evidence.json` with full stage timeline, command outputs, binary hash, verdict, and disclosures.

### Verdict vocabulary

| Verdict | Meaning |
|---------|---------|
| `verified` | Rust builds, passes fmt/clippy/test, and every oracle case matches |
| `generated_unverified` | Rust generated and may build, but verification incomplete |
| `blocked` | Missing capability, consent, or prerequisites |
| `failed` | Pipeline failed after exhausting repair budget |
| `cancelled` | Cancelled by user |

## Install

```bash
pip install https://github.com/pilkquant/pointer/releases/download/v0.2.1/pointer_cli-0.2.1-py3-none-any.whl
```

PyPI installation with `pip install pointer-cli` will become available after the repository's trusted publisher is registered on PyPI.

Pointer has **zero runtime dependencies** — it uses only the Python standard library. Requires Python 3.11+.

For the `port` command you also need:

- **Rust toolchain** (cargo, rustc, clippy, rustfmt) — `rustup install stable`
- **OpenAI Codex CLI** — install and authenticate separately. Set `POINTER_CODEX_BIN` if not in PATH.

## Quick start

### Static analysis (v0.1)

```bash
# Analyze any Python repository
pointer analyze ./my-project

# Reports land in ./pointer-report/
ls pointer-report/
# report.md   report.json
```

### Porting (v0.2)

```bash
# Port with real Codex (requires authenticated Codex CLI)
pointer port ./my-project --target rust --agent codex --yes --allow-source-execution

# Check status of all runs
pointer status

# Resume an interrupted run
pointer continue <run-id>

# Re-verify a completed run
pointer verify <run-id>
```

### Using the fake backend (for testing)

```bash
# Use deterministic fake backend — no Codex, no network
pointer port ./my-project --target rust --agent fake --yes
```

## Oracle configuration

Create a `pointer.toml` in your project root to define executable oracle cases:

```toml
[port]
target = "rust"

[[oracle.cases]]
name = "basic"
command = ["python", "-m", "myapp", "1 + 2"]
expected_exit = 0

[[oracle.cases]]
name = "stdin"
command = ["python", "-m", "myapp"]
stdin = "3 * 4\n"
expected_exit = 0

[[oracle.cases]]
name = "error_path"
command = ["python", "-m", "myapp", "invalid"]
expected_exit = 1

[oracle.normalization]
strip_trailing_whitespace = true
normalize_newlines = true
```

Without `pointer.toml`, the port proceeds but cannot reach `verified` — it ends `generated_unverified`.

## Security model

Pointer is designed to handle untrusted repositories safely:

**Static analysis (`pointer analyze`):**
- No code execution. No network access. No telemetry.
- Symlink-safe traversal. Files outside the repository root are never followed.
- All analysis uses stdlib `ast.parse()` on file contents.

**Porting (`pointer port`):**
- **Source execution is a separate security boundary.** `pointer port` contacts the agent by default, but does NOT execute your Python source unless you pass `--allow-source-execution`.
- **Codex runs in sandbox.** The agent operates only inside an isolated output workspace with `--sandbox workspace-write`. Never uses `--dangerously-bypass-approvals-and-sandbox`.
- **Secret redaction.** Likely secrets (API keys, tokens, passwords) are redacted from all logs and reports.
- **Sanitized environment.** Subprocess execution uses a documented env allowlist — no secret env vars leaked.
- **No symlinks followed outside allowed roots.**
- **Size limits** on all outputs and logs.
- **Path validation** before any destructive operation.
- **Source repository is never modified.**

See the [security tests](tests/test_port_security.py) for verifiable proof.

## CLI reference

```bash
pointer --help
pointer --version
pointer analyze PATH [options]
pointer port PATH [options]
pointer status [RUN_ID]
pointer continue RUN_ID
pointer verify RUN_ID
pointer doctor
```

### `pointer port`

```
pointer port ./my-project --target rust --agent codex [options]

Options:
  --target {rust}                 Target language (default: rust)
  --agent {codex,fake}            Agent backend (default: codex)
  --yes                           Auto-confirm (does NOT grant source execution)
  --allow-source-execution        Allow running Python source as oracle
  --max-repairs N                 Max repair attempts (default: 3)
  --state-root DIR                Override state directory
```

### `pointer status`

```
pointer status              # List all runs
pointer status <run-id>     # Show details for a specific run
pointer status --json       # JSON output
```

### `pointer analyze`

```
pointer analyze ./my-project [options]

Options:
  --target {compare,rust,cpp}  Target language for analysis (default: compare)
  --output, -o DIR             Output directory (default: pointer-report)
  --exclude GLOB               Additional exclude pattern (repeatable)
```

## Architecture

### Porting pipeline stages

```
preflight → analyze → oracle_capture → plan → generate →
native_build → differential_verify → repair → final_verify → complete
```

Each stage is:
- **Durable** — persisted to `state.json` atomically
- **Resumable** — completed stages are skipped on resume
- **Evidence-backed** — command outputs, durations, and artifacts recorded

### Agent backend protocol

The `AgentBackend` protocol decouples Pointer from any specific AI agent:

```python
class AgentBackend(Protocol):
    def probe(self) -> BackendCapabilities: ...
    def generate(self, prompt, workspace, *, timeout) -> AgentResult: ...
    def repair(self, prompt, workspace, *, session_id, timeout) -> AgentResult: ...
```

- **CodexBackend** — invokes `codex exec --json --sandbox=workspace-write` inside the isolated workspace
- **FakeBackend** — writes real compilable Rust for testing without network

### Example fixture

See [`examples/tinycalc/`](examples/tinycalc/) — a minimal arithmetic calculator with:
- A CLI accepting arguments and stdin
- Deterministic stdout and exit behavior
- Unit tests
- 8 oracle cases including error paths

## What the report tells you

Every analysis report answers nine questions across Markdown and JSON:

1. **Repository profile** — project name, version, Python requirement, file/line counts
2. **Packaging & layout** — build backends, lockfiles, source roots, entry points
3. **Native extension status** — pure Python or already partly native?
4. **Imports & dependencies** — full import inventory with portability dispositions
5. **Dynamic language blockers** — eval, exec, metaclasses, monkeypatching
6. **Test & oracle evidence** — test framework detection, oracle-readiness assessment
7. **Migration seams** — recommended module boundaries for incremental porting
8. **Target recommendation** — transparent Rust-vs-C++ scoring
9. **Evidence taxonomy** — every finding labeled observed, inferred, or unknown

## Limitations

- Dynamic Python behavior (reflection, monkeypatching) cannot be fully captured
- Nondeterministic outputs cannot be verified
- Network-dependent behavior may differ between Python and Rust
- Database, GUI, and distributed system ports are out of scope
- Native C/Fortran dependencies require manual handling
- Pointer does not port to C++ (v0.2 — Rust only)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Pointer is developed test-first with 221+ tests covering static analysis, porting, security, determinism, and integration.

## Maintenance

Pointer is maintained by **Madoka** under PilkQuant. See [MAINTAINERS.md](MAINTAINERS.md) for ownership and release responsibilities.

## License

[Apache License 2.0](LICENSE)
