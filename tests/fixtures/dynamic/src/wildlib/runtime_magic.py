"""Dynamic constructs that complicate porting."""

import importlib
import sys


def run_code(code_str: str):
    """Execute arbitrary code."""
    result = eval(code_str)
    exec(code_str)
    return result


def load_plugin(name: str):
    """Dynamically import a module."""
    module = importlib.import_module(name)
    return module


class MetaDict(type):
    """Custom metaclass."""

    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        return cls


class DynamicClass(metaclass=MetaDict):
    """Class using metaclass."""
    pass


class FlexibleConfig:
    """Dynamic attribute access."""

    def __getattr__(self, name):
        return f"default_for_{name}"


def patch_system():
    """Monkeypatch sys module."""
    sys.custom_attr = "injected"
    sys.exit = lambda code=0: None
    return sys.exit


DynamicType = type("DynamicType", (object,), {"value": 42})


def compile_snippet(source: str):
    """Compile code at runtime."""
    return compile(source, "<string>", "exec")
