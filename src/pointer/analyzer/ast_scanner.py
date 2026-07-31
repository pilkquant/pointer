"""AST-based Python source scanner.

Parses Python files using stdlib `ast` module — never imports or executes target code.
Inventories imports, detects dynamic language blockers, and measures type annotation coverage.
"""

from __future__ import annotations

import ast
from pathlib import Path

from pointer.analyzer.filesystem import PY_SUFFIXES, read_text_safely, safe_walk
from pointer.models import AstAnalysis, DynamicBlocker, ImportRecord

# A curated set of stdlib module names for classification.
# This is intentionally not exhaustive — it covers the most commonly used modules.
STDLIB_MODULES = frozenset(
    {
        "abc",
        "argparse",
        "array",
        "ast",
        "asynchat",
        "asyncio",
        "asyncore",
        "atexit",
        "base64",
        "bdb",
        "binascii",
        "binhex",
        "bisect",
        "builtins",
        "bz2",
        "calendar",
        "cgi",
        "cgitb",
        "chunk",
        "cmath",
        "cmd",
        "code",
        "codecs",
        "codeop",
        "collections",
        "colorsys",
        "compileall",
        "concurrent",
        "configparser",
        "contextlib",
        "contextvars",
        "copy",
        "copyreg",
        "cProfile",
        "crypt",
        "csv",
        "ctypes",
        "curses",
        "dataclasses",
        "datetime",
        "dbm",
        "decimal",
        "difflib",
        "dis",
        "distutils",
        "doctest",
        "email",
        "encodings",
        "enum",
        "errno",
        "faulthandler",
        "fcntl",
        "filecmp",
        "fileinput",
        "fnmatch",
        "fractions",
        "ftplib",
        "functools",
        "gc",
        "genericpath",
        "getopt",
        "getpass",
        "gettext",
        "glob",
        "graphlib",
        "grp",
        "gzip",
        "hashlib",
        "heapq",
        "hmac",
        "html",
        "http",
        "idlelib",
        "imaplib",
        "imghdr",
        "imp",
        "importlib",
        "inspect",
        "io",
        "ipaddress",
        "itertools",
        "json",
        "keyword",
        "lib2to3",
        "linecache",
        "locale",
        "logging",
        "lzma",
        "mailbox",
        "mailcap",
        "marshal",
        "math",
        "mimetypes",
        "mmap",
        "modulefinder",
        "multiprocessing",
        "netrc",
        "nis",
        "nntplib",
        "numbers",
        "operator",
        "optparse",
        "os",
        "ossaudiodev",
        "pathlib",
        "pdb",
        "pickle",
        "pickletools",
        "pipes",
        "pkgutil",
        "platform",
        "plistlib",
        "poplib",
        "posix",
        "posixpath",
        "pprint",
        "profile",
        "pstats",
        "pty",
        "pwd",
        "py_compile",
        "pyclbr",
        "pydoc",
        "pydoc_data",
        "queue",
        "quopri",
        "random",
        "re",
        "readline",
        "reprlib",
        "resource",
        "rlcompleter",
        "runpy",
        "sched",
        "secrets",
        "select",
        "selectors",
        "shelve",
        "shlex",
        "shutil",
        "signal",
        "site",
        "smtpd",
        "smtplib",
        "sndhdr",
        "socket",
        "socketserver",
        "spwd",
        "sqlite3",
        "ssl",
        "stat",
        "statistics",
        "string",
        "stringprep",
        "struct",
        "subprocess",
        "sunau",
        "symtable",
        "sys",
        "sysconfig",
        "syslog",
        "tabnanny",
        "tarfile",
        "telnetlib",
        "tempfile",
        "termios",
        "test",
        "textwrap",
        "threading",
        "time",
        "timeit",
        "tkinter",
        "token",
        "tokenize",
        "tomllib",
        "trace",
        "traceback",
        "tracemalloc",
        "tty",
        "turtle",
        "turtledemo",
        "types",
        "typing",
        "unicodedata",
        "unittest",
        "urllib",
        "uu",
        "uuid",
        "venv",
        "warnings",
        "wave",
        "weakref",
        "webbrowser",
        "winreg",
        "winsound",
        "wsgiref",
        "xdrlib",
        "xml",
        "xmlrpc",
        "zipapp",
        "zipfile",
        "zipimport",
        "zlib",
        "zoneinfo",
    }
)

# Dynamic blocker detection: AST node types and names to flag
# category → description mapping
DYNAMIC_BLOCKER_INFO = {
    "eval": ("Built-in eval() executes arbitrary code at runtime", "high"),
    "exec": ("Built-in exec() executes arbitrary code at runtime", "high"),
    "compile": ("compile() generates code objects at runtime", "medium"),
    "__import__": ("Dynamic __import__() loads modules at runtime", "medium"),
    "importlib.import_module": (
        "Dynamic importlib.import_module() loads modules at runtime",
        "medium",
    ),
    "globals": ("globals() accesses runtime module namespace", "low"),
    "locals": ("locals() accesses runtime local namespace", "low"),
    "vars": ("vars() accesses runtime namespace", "low"),
    "getattr": ("getattr() performs dynamic attribute access", "low"),
    "setattr": ("setattr() performs dynamic attribute mutation", "medium"),
    "delattr": ("delattr() performs dynamic attribute deletion", "medium"),
    "hasattr": ("hasattr() performs dynamic attribute probing", "low"),
    "type": ("Dynamic type() call — may create types at runtime", "medium"),
}


class _ImportVisitor(ast.NodeVisitor):
    """Collect import records from an AST."""

    def __init__(self, filename: str):
        self.filename = filename
        self.imports: list[ImportRecord] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0] if alias.name else alias.name
            self.imports.append(
                ImportRecord(
                    module=top,
                    name=None,
                    file=self.filename,
                    line=node.lineno,
                    kind="import",
                )
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            top = node.module.split(".")[0]
            # For relative imports, mark as local
            if node.level and node.level > 0:
                for alias in node.names:
                    self.imports.append(
                        ImportRecord(
                            module=node.module or ".",
                            name=alias.name,
                            file=self.filename,
                            line=node.lineno,
                            kind="from",
                        )
                    )
            else:
                for alias in node.names:
                    self.imports.append(
                        ImportRecord(
                            module=top,
                            name=alias.name,
                            file=self.filename,
                            line=node.lineno,
                            kind="from",
                        )
                    )
        self.generic_visit(node)


class _DynamicBlockerVisitor(ast.NodeVisitor):
    """Detect dynamic language constructs that complicate porting."""

    def __init__(self, filename: str):
        self.filename = filename
        self.blockers: list[DynamicBlocker] = []
        self.decorators: dict[str, int] = {}
        self._func_count = 0
        self._annotated_func_count = 0

    def _get_source_segment(self, node: ast.AST, source: str) -> str:
        """Get a short source snippet for a node."""
        if hasattr(node, "lineno"):
            try:
                lines = source.splitlines()
                if node.lineno <= len(lines):
                    return lines[node.lineno - 1].strip()[:120]
            except Exception:
                pass
        return ""

    def _check_call(self, node: ast.Call, source: str) -> None:
        """Check if a function call is a dynamic blocker."""
        func = node.func

        # Direct name calls: eval(), exec(), etc.
        if isinstance(func, ast.Name) and func.id in DYNAMIC_BLOCKER_INFO:
            desc, severity = DYNAMIC_BLOCKER_INFO[func.id]
            self.blockers.append(
                DynamicBlocker(
                    category=func.id,
                    file=self.filename,
                    line=node.lineno,
                    snippet=self._get_source_segment(node, source),
                    severity=severity,
                    description=desc,
                )
            )

        # Attribute calls: importlib.import_module, etc.
        elif isinstance(func, ast.Attribute):
            full_name = self._get_attr_name(func)
            if full_name and full_name in DYNAMIC_BLOCKER_INFO:
                desc, severity = DYNAMIC_BLOCKER_INFO[full_name]
                self.blockers.append(
                    DynamicBlocker(
                        category=full_name,
                        file=self.filename,
                        line=node.lineno,
                        snippet=self._get_source_segment(node, source),
                        severity=severity,
                        description=desc,
                    )
                )

    def _get_attr_name(self, node: ast.Attribute) -> str | None:
        """Get the dotted name from an Attribute node."""
        parts: list[str] = []
        current: ast.AST = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
        return None

    def visit_Call(self, node: ast.Call) -> None:
        self._check_call(node, self._current_source)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Check for metaclass keyword
        for keyword in node.keywords:
            if keyword.arg == "metaclass":
                ast.dump(keyword.value)
                self.blockers.append(
                    DynamicBlocker(
                        category="metaclass",
                        file=self.filename,
                        line=node.lineno,
                        snippet=f"class {node.name}(...)",
                        severity="high",
                        description=(
                            "Metaclass usage detected — custom metaclass complicates static analysis and porting"
                        ),
                    )
                )

        # Check for __getattr__ method
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__getattr__":
                self.blockers.append(
                    DynamicBlocker(
                        category="__getattr__",
                        file=self.filename,
                        line=item.lineno,
                        severity="medium",
                        description=("__getattr__ enables dynamic attribute resolution — complicates static analysis"),
                    )
                )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._func_count += 1

        # Check type annotation coverage
        if node.returns is not None or any(arg.annotation is not None for arg in node.args.args):
            self._annotated_func_count += 1

        # Collect decorator names
        for dec in node.decorator_list:
            name = self._decorator_name(dec)
            if name:
                self.decorators[name] = self.decorators.get(name, 0) + 1

        # Check for monkeypatch-like attribute assignment in function body
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Attribute) and target.attr not in (
                        "value",
                        "next",
                        "self",  # common instance attribute
                    ):
                        # Detect monkeypatch: assigning to an attribute on
                        # something that is itself an attribute (module.class.x = ...)
                        # or a Name that looks like an imported module (sys.x = ...)
                        if isinstance(target.value, ast.Attribute):
                            attr_chain = self._get_attr_name(target.value)
                            if attr_chain and "." in attr_chain:
                                self.blockers.append(
                                    DynamicBlocker(
                                        category="monkeypatch",
                                        file=self.filename,
                                        line=child.lineno,
                                        snippet=self._get_source_segment(child, self._current_source),
                                        severity="medium",
                                        description=(
                                            f"Attribute assignment to '{attr_chain}.{target.attr}'"
                                            " — potential monkeypatching"
                                        ),
                                    )
                                )
                        elif isinstance(target.value, ast.Name):
                            # e.g., sys.custom_attr = ... or os.path = ...
                            mod_name = target.value.id
                            if mod_name in (
                                "sys",
                                "os",
                                "builtins",
                                "importlib",
                                "inspect",
                                "types",
                                "functools",
                                "collections",
                            ):
                                self.blockers.append(
                                    DynamicBlocker(
                                        category="monkeypatch",
                                        file=self.filename,
                                        line=child.lineno,
                                        snippet=self._get_source_segment(child, self._current_source),
                                        severity="medium",
                                        description=(
                                            f"Attribute assignment to '{mod_name}.{target.attr}'"
                                            f" — potential monkeypatching of {mod_name}"
                                        ),
                                    )
                                )

        self.generic_visit(node)

    def _decorator_name(self, node: ast.AST) -> str | None:
        """Extract decorator name."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return self._get_attr_name(node)
        elif isinstance(node, ast.Call):
            return self._decorator_name(node.func)
        return None

    # Store current source for snippet extraction
    _current_source: str = ""


def scan_python(root: Path) -> AstAnalysis:
    """Scan all Python files in root and collect AST analysis."""
    analysis = AstAnalysis()
    all_files = safe_walk(root)

    all_imports: list[ImportRecord] = []
    all_blockers: list[DynamicBlocker] = []
    all_decorator_usage: dict[str, int] = {}
    total_funcs = 0
    annotated_funcs = 0

    for fpath, rel in all_files:
        if fpath.suffix not in PY_SUFFIXES or fpath.suffix == ".pyi":
            continue

        analysis.total_py_files += 1
        source = read_text_safely(fpath)
        if source is None:
            continue

        # Parse AST
        try:
            tree = ast.parse(source, filename=rel, type_comments=True)
        except SyntaxError as e:
            analysis.files_with_syntax_errors.append(f"{rel}:{e.lineno}:{e.msg}")
            continue
        except ValueError as e:
            analysis.files_with_syntax_errors.append(f"{rel}:{e}")
            continue

        # Collect imports
        imp_visitor = _ImportVisitor(rel)
        imp_visitor.visit(tree)
        all_imports.extend(imp_visitor.imports)

        # Collect dynamic blockers
        blocker_visitor = _DynamicBlockerVisitor(rel)
        blocker_visitor._current_source = source
        blocker_visitor.visit(tree)
        all_blockers.extend(blocker_visitor.blockers)

        # Aggregate decorators
        for name, count in blocker_visitor.decorators.items():
            all_decorator_usage[name] = all_decorator_usage.get(name, 0) + count

        total_funcs += blocker_visitor._func_count
        annotated_funcs += blocker_visitor._annotated_func_count

    # Classify imports
    analysis.imports = all_imports
    external_set: set[str] = set()
    stdlib_set: set[str] = set()
    local_set: set[str] = set()

    for imp in all_imports:
        if imp.module == "." or imp.module == "":
            local_set.add("(relative)")
            continue
        if imp.module in STDLIB_MODULES:
            stdlib_set.add(imp.module)
        else:
            # Heuristic: could be local or external.
            # We classify as external; local determination requires structure context.
            external_set.add(imp.module)

    analysis.external_imports = sorted(external_set)
    analysis.stdlib_imports = sorted(stdlib_set)
    analysis.local_imports = sorted(local_set)
    analysis.dynamic_blockers = all_blockers
    analysis.decorator_usage = dict(sorted(all_decorator_usage.items(), key=lambda x: -x[1]))
    if total_funcs > 0:
        analysis.type_annotation_coverage = round(annotated_funcs / total_funcs, 3)

    return analysis
