"""Curated dependency disposition knowledge base.

Each entry provides a porting disposition for a common Python package,
with provenance and confidence. Unknown dependencies are NEVER fabricated.

Dispositions:
- direct_replacement: a near-drop-in Rust/C++ crate/library exists
- adapt: similar functionality exists but API differs significantly
- ffi_wrap: can be called via FFI from native code
- keep_python: best kept on the Python side of a hybrid boundary
- rewrite: no equivalent exists; must be rewritten from scratch
- blocker: blocks native porting of its consumer
- unknown: insufficient information (never fabricated)
"""

from __future__ import annotations

from pointer.models import Confidence, DepDisposition

# Schema version for the knowledge base itself
KB_VERSION = "0.1.0"

# The curated knowledge base.
# Each tuple: (package_name, disposition, rust_notes, cpp_notes, provenance, confidence)
_KB_DATA: list[tuple[str, str, str, str, str, Confidence]] = [
    # --- Standard library-adjacent ---
    (
        "numpy",
        "ffi_wrap",
        "PyO3 bindings (numpy crate) or pyo3/numpy. ndarray + nalgebra for pure Rust.",
        "xtensor provides NumPy-like arrays. OpenCV for image arrays.",
        "PyO3 numpy bindings: https://pyo3.rs; xtensor: https://xtensor-stack.github.io",
        Confidence.HIGH,
    ),
    (
        "scipy",
        "keep_python",
        "Large surface area; individual functions may use nalgebra/numpy. Full replacement impractical.",
        "Similar — Eigen/Boost for specific algorithms.",
        "scipy depends on numpy and Fortran routines; partial FFI possible.",
        Confidence.HIGH,
    ),
    (
        "pandas",
        "adapt",
        "Polars is a Rust-native DataFrame library with Python bindings; similar API but not drop-in.",
        "No direct C++ equivalent; Apache Arrow C++ for columnar data.",
        "Polars: https://pola.rs/ — Rust DataFrame engine",
        Confidence.HIGH,
    ),
    (
        "polars",
        "direct_replacement",
        "Polars is already Rust-native. Use directly.",
        "Apache Arrow/DataFrame equivalents exist but differ.",
        "Polars is written in Rust: https://github.com/pola-rs/polars",
        Confidence.HIGH,
    ),
    # --- Web frameworks ---
    (
        "fastapi",
        "adapt",
        "axum or actix-web for similar async HTTP frameworks. Different API.",
        "cpp-httplib or Crow for basic HTTP; Drogon for full-featured.",
        "axum: https://github.com/tokio-rs/axum; Drogon: https://github.com/drogonframework/drogon",
        Confidence.MEDIUM,
    ),
    (
        "flask",
        "adapt",
        "axum, actix-web, or Rocket for web servers. Different paradigm.",
        "Crow, cpp-httplib, or Drogon.",
        "Rocket: https://rocket.rs; Flask is WSGI-based.",
        Confidence.MEDIUM,
    ),
    (
        "django",
        "keep_python",
        "Full-stack framework with ORM, admin, auth — impractical to port wholesale.",
        "Same — no equivalent full-stack C++ web framework.",
        "Django is a batteries-included framework tightly coupled to Python.",
        Confidence.HIGH,
    ),
    (
        "starlette",
        "adapt",
        "axum or actix-web for async ASGI-equivalent.",
        "Drogon for async HTTP.",
        "Starlette is the ASGI toolkit underlying FastAPI.",
        Confidence.MEDIUM,
    ),
    (
        "uvicorn",
        "keep_python",
        "ASGI server — stay in Python; native code would be a reverse proxy (nginx/envoy).",
        "Same perspective.",
        "uvicorn is a Python ASGI server.",
        Confidence.HIGH,
    ),
    (
        "aiohttp",
        "adapt",
        "reqwest (client) or actix-web/axum (server) for HTTP in Rust.",
        "cpp-httplib, cpr for HTTP client.",
        "reqwest: https://github.com/seanmonstar/reqwest",
        Confidence.MEDIUM,
    ),
    (
        "requests",
        "adapt",
        "reqwest is the standard Rust HTTP client. Similar but not identical API.",
        "cpr (C++ Requests) mirrors the requests API.",
        "reqwest: https://github.com/seanmonstar/reqwest; cpr: https://github.com/libcpr/cpr",
        Confidence.HIGH,
    ),
    (
        "httpx",
        "adapt",
        "reqwest for sync/async HTTP client.",
        "cpr or Boost.Beast.",
        "httpx is the modern Python HTTP client.",
        Confidence.MEDIUM,
    ),
    # --- Data validation ---
    (
        "pydantic",
        "adapt",
        "serde for serialization; no direct validation framework equivalent. pydantic-core is already Rust.",
        "No direct equivalent; manual validation or Boost.",
        "pydantic-core uses Rust internally: https://github.com/pydantic/pydantic-core",
        Confidence.HIGH,
    ),
    (
        "marshmallow",
        "adapt",
        "serde + serde_json for serialization/deserialization.",
        "nlohmann/json + manual validation.",
        "serde: https://serde.rs",
        Confidence.MEDIUM,
    ),
    # --- Databases ---
    (
        "sqlalchemy",
        "adapt",
        "diesel or sqlx for SQL ORM/query building.",
        "SQLite C API, or SOCI for multi-DB.",
        "diesel: https://diesel.rs; sqlx: https://github.com/launchbadge/sqlx",
        Confidence.MEDIUM,
    ),
    (
        "asyncpg",
        "adapt",
        "sqlx or tokio-postgres for async PostgreSQL.",
        "libpq (C library) directly.",
        "tokio-postgres: https://github.com/sfackler/rust-postgres",
        Confidence.HIGH,
    ),
    (
        "psycopg2",
        "ffi_wrap",
        "Can use libpq directly via FFI.",
        "libpq C API directly.",
        "psycopg2 wraps libpq.",
        Confidence.HIGH,
    ),
    (
        "redis",
        "adapt",
        "redis-rs is the standard Rust Redis client.",
        "redis-plus-plus or hiredis.",
        "redis-rs: https://github.com/redis-rs/redis-rs",
        Confidence.HIGH,
    ),
    (
        "pymongo",
        "adapt",
        "mongodb Rust driver is official.",
        "mongocxx official C++ driver.",
        "mongodb-rust: https://github.com/mongodb/mongo-rust-driver",
        Confidence.HIGH,
    ),
    # --- Serialization ---
    (
        "orjson",
        "direct_replacement",
        "serde_json is already faster in Rust.",
        "simdjson or rapidjson for C++.",
        "serde_json: https://serde.rs; orjson is already Rust-backed internally.",
        Confidence.HIGH,
    ),
    (
        "ujson",
        "adapt",
        "serde_json for JSON.",
        "simdjson or rapidjson.",
        "ultrajson is C-based; serde_json is Rust-native.",
        Confidence.MEDIUM,
    ),
    (
        "msgpack",
        "adapt",
        "rmp-serde for MessagePack.",
        "msgpack-c official C++ library.",
        "rmp-serde: https://github.com/3Hren/msgpack-rust",
        Confidence.HIGH,
    ),
    (
        "protobuf",
        "adapt",
        "prost for Protocol Buffers in Rust.",
        "Google protobuf C++ library (official).",
        "prost: https://github.com/tokio-rs/prost",
        Confidence.HIGH,
    ),
    # --- Async/concurrency ---
    (
        "celery",
        "rewrite",
        "No direct Rust equivalent; must architect from tokio + Redis/RabbitMQ.",
        "No direct C++ equivalent.",
        "Celery is a Python-specific task queue pattern.",
        Confidence.MEDIUM,
    ),
    (
        "asyncio",
        "adapt",
        "tokio or async-std for async runtime.",
        "Boost.Asio or libuv for async.",
        "tokio: https://tokio.rs",
        Confidence.HIGH,
    ),
    # --- CLI ---
    (
        "click",
        "adapt",
        "clap is the standard Rust CLI parser.",
        "CLI11 or cxxopts for C++.",
        "clap: https://github.com/clap-rs/clap; CLI11: https://github.com/CLIUtils/CLI11",
        Confidence.HIGH,
    ),
    (
        "typer",
        "adapt",
        "clap with derive macros provides similar type-driven CLI.",
        "CLI11.",
        "clap derive: https://docs.rs/clap",
        Confidence.MEDIUM,
    ),
    (
        "argparse",
        "adapt",
        "clap for Rust.",
        "CLI11 or cxxopts.",
        "stdlib argparse maps to clap features.",
        Confidence.HIGH,
    ),
    # --- Crypto/hashing ---
    (
        "cryptography",
        "ffi_wrap",
        "RustCrypto crates or OpenSSL FFI.",
        "OpenSSL C API directly.",
        "cryptography package is already OpenSSL/OpenSSL-Rust backed.",
        Confidence.HIGH,
    ),
    (
        "bcrypt",
        "direct_replacement",
        "bcrypt crate is available.",
        "cryptopp or libbcrypt.",
        "bcrypt crate: https://crates.io/crates/bcrypt",
        Confidence.HIGH,
    ),
    (
        "hashlib",
        "direct_replacement",
        "sha2, md5, blake2 crates in RustCrypto.",
        "OpenSSL EVP or cryptopp.",
        "RustCrypto: https://github.com/RustCrypto/hashes",
        Confidence.HIGH,
    ),
    # --- ML/Data Science ---
    (
        "torch",
        "keep_python",
        "tch-rs provides PyTorch bindings, but PyTorch itself remains the runtime.",
        "libtorch C++ API directly.",
        "PyTorch is a C++ core with Python bindings; tch-rs wraps libtorch.",
        Confidence.HIGH,
    ),
    (
        "tensorflow",
        "keep_python",
        "tensorflow-rust exists but lags behind. TF C++ API is available.",
        "TensorFlow C++ API is official.",
        "TF core is C++; Python is the primary frontend.",
        Confidence.HIGH,
    ),
    (
        "scikit-learn",
        "keep_python",
        "linfa is an emerging Rust ML toolkit but incomplete vs sklearn.",
        "mlpack or dlib for C++ ML.",
        "linfa: https://github.com/rust-ml/linfa; sklearn is heavily Python+NumPy.",
        Confidence.MEDIUM,
    ),
    (
        "transformers",
        "keep_python",
        "candle (Hugging Face) provides Rust transformers but incomplete coverage.",
        "No good C++ equivalent for high-level API.",
        "candle: https://github.com/huggingface/candle",
        Confidence.MEDIUM,
    ),
    # --- Logging ---
    (
        "logging",
        "direct_replacement",
        "tracing or log crate.",
        "spdlog for C++.",
        "tracing: https://github.com/tokio-rs/tracing; spdlog: https://github.com/gabime/spdlog",
        Confidence.HIGH,
    ),
    (
        "structlog",
        "adapt",
        "tracing with structured fields.",
        "spdlog with custom formatter.",
        "structlog adds structured logging on top of stdlib.",
        Confidence.MEDIUM,
    ),
    (
        "loguru",
        "adapt",
        "tracing or env_logger.",
        "spdlog.",
        "loguru is a popular single-file logger.",
        Confidence.MEDIUM,
    ),
    # --- Testing ---
    (
        "pytest",
        "keep_python",
        "Testing framework — stays on Python side for oracle verification.",
        "Google Test or Catch2 for C++ tests.",
        "pytest is the Python test runner; native tests use native frameworks.",
        Confidence.HIGH,
    ),
    (
        "hypothesis",
        "keep_python",
        "proptest for Rust property testing (different API).",
        "rapidcheck for C++.",
        "proptest: https://github.com/proptest-rs/proptest",
        Confidence.HIGH,
    ),
    # --- Utilities ---
    (
        "pyyaml",
        "adapt",
        "serde_yaml for YAML.",
        "yaml-cpp.",
        "serde_yaml: https://docs.rs/serde_yaml; yaml-cpp: https://github.com/jbeder/yaml-cpp",
        Confidence.HIGH,
    ),
    (
        "tomli",
        "direct_replacement",
        "toml crate.",
        "toml++ for C++.",
        "toml: https://github.com/toml-rs/toml-rs",
        Confidence.HIGH,
    ),
    (
        "pillow",
        "adapt",
        "image crate for Rust.",
        "OpenCV, stb_image, or libvips.",
        "image crate: https://github.com/image-rs/image",
        Confidence.HIGH,
    ),
    ("requests", "adapt", "reqwest for HTTP client.", "cpr (C++ Requests).", "Already covered above.", Confidence.HIGH),
    (
        "rich",
        "adapt",
        "ratatui or colored for terminal output.",
        "No great equivalent; ANSI codes manually.",
        "ratatui: https://github.com/ratatui-org/ratatui",
        Confidence.MEDIUM,
    ),
    (
        "tenacity",
        "adapt",
        "backoff crate for retry logic.",
        "No standard; Boost.Asio timers or manual.",
        "backoff: https://crates.io/crates/backoff",
        Confidence.MEDIUM,
    ),
    (
        "python-dateutil",
        "adapt",
        "chrono crate provides date parsing with locale support.",
        "date or Howard Hinnant's date library.",
        "chrono: https://github.com/chronotope/chrono",
        Confidence.HIGH,
    ),
    (
        "pytz",
        "direct_replacement",
        "chrono-tz for timezone database.",
        "Howard Hinnant date library with tz_db.",
        "chrono-tz: https://crates.io/crates/chrono-tz",
        Confidence.HIGH,
    ),
    (
        "attrs",
        "adapt",
        "serde + builder pattern or derive crate.",
        "No direct equivalent; manual structs.",
        "attrs provides declarative data classes.",
        Confidence.MEDIUM,
    ),
    (
        "jinja2",
        "adapt",
        "tera or askama for templating.",
        "inja for C++ templating.",
        "tera: https://crate.io/crates/tera; askama: https://djc.github.io/askama",
        Confidence.HIGH,
    ),
    # --- File/IO ---
    (
        "boto3",
        "keep_python",
        "aws-sdk-rust exists but covers different services/API surface.",
        "AWS SDK for C++ exists but complex.",
        "boto3 wraps the full AWS API; SDK coverage varies.",
        Confidence.MEDIUM,
    ),
    # --- Misc common ---
    (
        "six",
        "direct_replacement",
        "Irrelevant — Python 2 compat not needed in native.",
        "Same.",
        "six is Python 2/3 compat; not applicable to native ports.",
        Confidence.HIGH,
    ),
    (
        "setuptools",
        "keep_python",
        "Build tooling — stays on Python side.",
        "Build tooling.",
        "setuptools is Python packaging.",
        Confidence.HIGH,
    ),
    (
        "pip",
        "keep_python",
        "Package manager — stays on Python side.",
        "Package manager.",
        "pip is Python-specific.",
        Confidence.HIGH,
    ),
    (
        "wheel",
        "keep_python",
        "Build tooling — stays on Python side.",
        "Build tooling.",
        "wheel is Python packaging.",
        Confidence.HIGH,
    ),
]


def get_kb() -> list[DepDisposition]:
    """Return the full knowledge base as DepDisposition objects."""
    return [
        DepDisposition(
            name=name,
            disposition=disposition,
            rust_notes=rust_notes,
            cpp_notes=cpp_notes,
            provenance=provenance,
            confidence=confidence,
        )
        for name, disposition, rust_notes, cpp_notes, provenance, confidence in _KB_DATA
    ]


def lookup(name: str) -> DepDisposition | None:
    """Look up a single package by name."""
    for entry in _KB_DATA:
        if entry[0] == name:
            return DepDisposition(
                name=entry[0],
                disposition=entry[1],
                rust_notes=entry[2],
                cpp_notes=entry[3],
                provenance=entry[4],
                confidence=entry[5],
            )
    return None


def disposition_for_imports(external_imports: list[str], project_dependencies: list[str]) -> list[DepDisposition]:
    """Match external imports and declared dependencies against the knowledge base.

    Returns matched dispositions plus unknown entries for unmatched ones.
    Never fabricates replacements — unmatched deps are marked 'unknown'.
    """
    results: list[DepDisposition] = []
    seen: set[str] = set()

    # Combine both sources of dependency names
    # Extract package names from dependency specs (e.g., "requests>=2.0" → "requests")
    dep_names: set[str] = set()
    for dep in project_dependencies:
        # Strip version specifiers
        clean = dep.split(">")[0].split("<")[0].split("=")[0].split("!")[0].split("[")[0].split(";")[0]
        clean = clean.strip().lower().replace("-", "_").replace(" ", "")
        if clean:
            dep_names.add(clean)

    for imp in external_imports:
        clean = imp.lower().replace("-", "_")
        dep_names.add(clean)

    for name in sorted(dep_names):
        if name in seen:
            continue
        seen.add(name)

        disposition = lookup(name)
        if disposition:
            results.append(disposition)
        else:
            results.append(
                DepDisposition(
                    name=name,
                    disposition="unknown",
                    provenance=f"Not in Pointer's curated knowledge base (v{KB_VERSION}). Manual research required.",
                    confidence=Confidence.LOW,
                )
            )

    return results
