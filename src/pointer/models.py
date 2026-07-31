"""Typed data models for all Pointer analysis and report structures.

Every model is a dataclass with explicit fields. JSON serialization is handled
by report.json_out via dataclasses.asdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Confidence(StrEnum):
    """Confidence level for a finding."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Evidence(StrEnum):
    """How a finding was determined."""

    OBSERVED = "observed"  # directly detected in the repo
    INFERRED = "inferred"  # deduced from signals
    UNKNOWN = "unknown"  # not enough data


class Target(StrEnum):
    """Porting target for analysis."""

    COMPARE = "compare"
    RUST = "rust"
    CPP = "cpp"


@dataclass
class FileEntry:
    """A discovered file with its relative path."""

    path: str
    kind: str  # e.g. "pyproject", "requirements", "lockfile", "python", "native", "test", "config"


@dataclass
class BuildSystem:
    """Detected build/packaging system."""

    name: str  # e.g. "setuptools", "hatchling", "maturin", "poetry"
    backend: str | None = None  # build-backend value from pyproject.toml
    evidence: Evidence = Evidence.OBSERVED
    source_file: str | None = None


@dataclass
class EntryPoint:
    """A CLI or GUI entry point."""

    name: str
    module: str
    attr: str
    group: str = "console"  # console_scripts, gui_scripts


@dataclass
class SourceRoot:
    """A source root directory."""

    path: str
    package_names: list[str] = field(default_factory=list)


@dataclass
class Lockfile:
    """A discovered lockfile."""

    path: str
    kind: str  # uv.lock, poetry.lock, pdm.lock, requirements.txt, pip-tools


@dataclass
class ProjectStructure:
    """Results of packaging/build discovery."""

    root: str
    project_name: str | None = None
    version: str | None = None
    build_systems: list[BuildSystem] = field(default_factory=list)
    lockfiles: list[Lockfile] = field(default_factory=list)
    entry_points: list[EntryPoint] = field(default_factory=list)
    source_roots: list[SourceRoot] = field(default_factory=list)
    requires_python: str | None = None
    dependencies: list[str] = field(default_factory=list)
    files: list[FileEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # raw pyproject.toml parsed data if available
    pyproject_data: dict[str, Any] | None = None


@dataclass
class ImportRecord:
    """A single import found in the AST."""

    module: str  # top-level module name
    name: str | None = None  # specific name imported, if discernible
    file: str = ""  # source file relative to root
    line: int = 0
    kind: str = "import"  # "import", "from", "dynamic"


@dataclass
class DynamicBlocker:
    """A dynamic language construct that complicates porting."""

    category: str  # "eval", "exec", "metaclass", "__getattr__", "monkeypatch", etc.
    file: str
    line: int
    snippet: str = ""
    severity: str = "medium"  # high/medium/low
    description: str = ""


@dataclass
class AstAnalysis:
    """Results of AST scanning."""

    imports: list[ImportRecord] = field(default_factory=list)
    external_imports: list[str] = field(default_factory=list)  # deduplicated top-level
    stdlib_imports: list[str] = field(default_factory=list)
    local_imports: list[str] = field(default_factory=list)
    dynamic_blockers: list[DynamicBlocker] = field(default_factory=list)
    total_py_files: int = 0
    files_with_syntax_errors: list[str] = field(default_factory=list)
    decorator_usage: dict[str, int] = field(default_factory=dict)
    type_annotation_coverage: float = 0.0  # fraction of functions with annotations


@dataclass
class NativeExtSignal:
    """A signal indicating native extension involvement."""

    kind: str  # "compiled_file", "build_backend", "source_reference", "wheel_tag"
    detail: str
    file: str | None = None
    evidence: Evidence = Evidence.OBSERVED


@dataclass
class NativeExtAnalysis:
    """Results of native extension detection."""

    has_native_extensions: bool = False
    signals: list[NativeExtSignal] = field(default_factory=list)
    build_backends_native: list[str] = field(default_factory=list)  # maturin, meson-python, etc.
    binding_tools: list[str] = field(default_factory=list)  # pyo3, pybind11, cffi, etc.


@dataclass
class CodeMetrics:
    """Code size metrics."""

    total_py_files: int = 0
    total_py_lines: int = 0
    total_py_logical_lines: int = 0  # non-blank, non-comment
    files_by_type: dict[str, int] = field(default_factory=dict)
    largest_files: list[dict[str, Any]] = field(default_factory=list)
    module_count: int = 0


@dataclass
class TestFileInfo:
    """Info about a discovered test file."""

    path: str
    framework: str = "unknown"


@dataclass
class TestAnalysis:
    """Test layout and oracle-readiness assessment."""

    test_files: list[TestFileInfo] = field(default_factory=list)
    test_dirs: list[str] = field(default_factory=list)
    frameworks_detected: list[str] = field(default_factory=list)
    has_conftest: bool = False
    has_fixtures: bool = False
    oracle_readiness: str = "unknown"  # high/medium/low/unknown
    oracle_readiness_reason: str = ""


@dataclass
class DepDisposition:
    """Disposition for a specific dependency."""

    name: str
    disposition: str  # direct_replacement, adapt, ffi_wrap, keep_python, rewrite, blocker, unknown
    rust_notes: str = ""
    cpp_notes: str = ""
    provenance: str = ""  # source of this claim
    confidence: Confidence = Confidence.MEDIUM


@dataclass
class ScoreFactor:
    """A single scoring factor for target recommendation."""

    name: str
    score: int  # -2 to +2 (negative favors staying in Python, positive favors native)
    rust_weight: int = 0  # additional rust-specific adjustment
    cpp_weight: int = 0  # additional cpp-specific adjustment
    reason: str = ""


@dataclass
class Recommendation:
    """Rust vs C++ vs hybrid vs stay-Python recommendation."""

    target: str  # rust, cpp, hybrid, stay_python, inconclusive
    confidence: Confidence = Confidence.MEDIUM
    rust_score: int = 0
    cpp_score: int = 0
    stay_python_score: int = 0
    factors: list[ScoreFactor] = field(default_factory=list)
    rationale: str = ""
    caveats: list[str] = field(default_factory=list)


@dataclass
class MigrationSeam:
    """A suggested migration boundary."""

    module: str
    reason: str
    priority: str = "medium"  # high/medium/low
    dependencies: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


@dataclass
class AnalysisReport:
    """The complete analysis report — top-level model."""

    schema_version: str = "0.1.0"
    pointer_version: str = "0.1.0"
    target: str = "compare"
    analysis_timestamp: str = ""
    root_path: str = ""
    structure: ProjectStructure | None = None
    ast_analysis: AstAnalysis | None = None
    native_ext: NativeExtAnalysis | None = None
    metrics: CodeMetrics | None = None
    tests: TestAnalysis | None = None
    dependency_dispositions: list[DepDisposition] = field(default_factory=list)
    recommendation: Recommendation | None = None
    migration_seams: list[MigrationSeam] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
