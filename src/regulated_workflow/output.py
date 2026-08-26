from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence


REVIEW_QUEUE_FIELDS = (
    "record_type",
    "source_id",
    "field",
    "value",
    "old_value",
    "new_value",
    "confidence",
    "risk_level",
    "reason",
    "review_status",
)


def write_json(path: Path, records: Sequence[Dict[str, Any]]) -> None:
    content = json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write_text(path, content)


def write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    lines = [json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records]
    _atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def write_csv(
    path: Path,
    rows: Sequence[Dict[str, Any]],
    fieldnames: Sequence[str] = REVIEW_QUEUE_FIELDS,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=".%s." % path.name,
        suffix=".tmp",
        dir=str(path.parent),
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(
                {
                    key: _spreadsheet_safe(row.get(key, ""))
                    for key in fieldnames
                }
                for row in rows
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temp_path), str(path))
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def write_text(path: Path, content: str) -> None:
    _atomic_write_text(path, content if content.endswith("\n") else content + "\n")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=".%s." % path.name,
        suffix=".tmp",
        dir=str(path.parent),
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temp_path), str(path))
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _spreadsheet_safe(value: Any) -> Any:
    """Prevent untrusted review text from becoming a spreadsheet formula."""
    if not isinstance(value, str) or not value:
        return value
    stripped = value.lstrip()
    if stripped.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r")):
        return "'" + value
    return value
