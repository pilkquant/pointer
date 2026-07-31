"""JSON report writer.

Produces deterministic, schema-versioned JSON from AnalysisReport.
Uses dataclasses.asdict with custom enum serialization.
"""

from __future__ import annotations

import json
from dataclasses import is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pointer.models import AnalysisReport


def _serialize(obj: Any) -> Any:
    """Recursively serialize dataclasses and enums for JSON."""
    if isinstance(obj, Enum):
        return obj.value
    elif is_dataclass(obj) and not isinstance(obj, type):
        result = {}
        for field_name, _field_def in obj.__dataclass_fields__.items():
            value = getattr(obj, field_name)
            result[field_name] = _serialize(value)
        return result
    elif isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    elif obj is None:
        return None
    return obj


def to_json(report: AnalysisReport) -> str:
    """Serialize an AnalysisReport to a deterministic JSON string."""
    data = _serialize(report)
    # Ensure consistent key ordering with sort_keys for determinism
    return json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False)


def write_json(report: AnalysisReport, output_dir: Path) -> Path:
    """Write report.json to the output directory. Returns the file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / "report.json"
    filepath.write_text(to_json(report) + "\n", encoding="utf-8")
    return filepath
