from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .errors import InputError, OptionalDependencyError
from .models import EvidenceItem


SUPPORTED_SUFFIXES = {".txt", ".md", ".csv", ".json", ".pdf"}
_KEY_VALUE_RE = re.compile(
    r"^(?:[-*+]\s*)?(?:\*\*)?([^:#]{1,80}?)(?:\*\*)?\s*:\s*(.+)$"
)


@dataclass(frozen=True)
class ParsedDocument:
    source_id: str
    format: str
    sha256: str
    byte_size: int
    evidence: Sequence[EvidenceItem]


def discover_documents(
    input_path: Path, exclude_paths: Optional[Iterable[Path]] = None
) -> List[Path]:
    candidate = input_path.expanduser()
    if not candidate.exists():
        raise InputError("input path does not exist: %s" % input_path)

    excluded = []
    for path in exclude_paths or []:
        try:
            excluded.append(path.expanduser().resolve())
        except OSError:
            continue

    if candidate.is_file():
        if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise InputError(
                "unsupported input format %s; supported formats: %s"
                % (candidate.suffix or "<none>", ", ".join(sorted(SUPPORTED_SUFFIXES)))
            )
        return [candidate]

    if not candidate.is_dir():
        raise InputError("input path must be a file or directory: %s" % input_path)

    documents = []
    for path in sorted(candidate.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        resolved = path.resolve()
        if any(_is_within(resolved, excluded_path) for excluded_path in excluded):
            continue
        documents.append(path)

    if not documents:
        raise InputError(
            "no supported documents found under %s (expected %s)"
            % (input_path, ", ".join(sorted(SUPPORTED_SUFFIXES)))
        )
    return documents


def read_documents(
    input_path: Path, exclude_paths: Optional[Iterable[Path]] = None
) -> List[ParsedDocument]:
    documents = discover_documents(input_path, exclude_paths=exclude_paths)
    root = input_path if input_path.is_dir() else input_path.parent
    parsed = []
    for path in documents:
        try:
            source_id = path.relative_to(root).as_posix()
        except ValueError:
            source_id = path.name
        parsed.append(read_document(path, source_id))
    return parsed


def read_document(path: Path, source_id: str) -> ParsedDocument:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise InputError("could not read %s: %s" % (source_id, exc)) from exc

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        items = _parse_pdf(path, source_id)
    else:
        text = _decode_utf8(payload, source_id)
        if suffix in {".txt", ".md"}:
            items = _parse_text(source_id, text)
        elif suffix == ".csv":
            items = _parse_csv(source_id, text)
        elif suffix == ".json":
            items = _parse_json(source_id, text)
        else:
            raise InputError("unsupported input format: %s" % suffix)

    return ParsedDocument(
        source_id=source_id,
        format=suffix.lstrip("."),
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_size=len(payload),
        evidence=tuple(_deduplicate_fields(items)),
    )


def _decode_utf8(payload: bytes, source_id: str) -> str:
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError("%s is not valid UTF-8 text" % source_id) from exc


def _parse_text(source_id: str, text: str, page: int = 1) -> List[EvidenceItem]:
    items = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        match = _KEY_VALUE_RE.match(line.lstrip("# "))
        if match:
            field = _clean_markdown(match.group(1))
            value = _clean_markdown(match.group(2))
            confidence = 0.9
        elif line.startswith("#"):
            field = "heading[%d]" % line_number
            value = line.lstrip("# ").strip()
            confidence = 0.75
        else:
            field = "text.line[%d]" % line_number
            value = line
            confidence = 0.6

        items.append(
            EvidenceItem(
                source_id=source_id,
                page=page,
                quote=line,
                field=field,
                value=value,
                confidence=confidence,
            )
        )
    return items


def _parse_csv(source_id: str, text: str) -> List[EvidenceItem]:
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        headers = reader.fieldnames
        if not headers:
            raise InputError("%s has no CSV header" % source_id)
        cleaned_headers = [header.strip() if header else "" for header in headers]
        if any(not header for header in cleaned_headers):
            raise InputError("%s contains an empty CSV header" % source_id)
        if len(set(cleaned_headers)) != len(cleaned_headers):
            raise InputError("%s contains duplicate CSV headers" % source_id)

        items = []
        for row_number, row in enumerate(reader, start=1):
            if None in row:
                raise InputError("%s row %d has too many columns" % (source_id, row_number))
            for original_header, clean_header in zip(headers, cleaned_headers):
                raw_value = row.get(original_header)
                value = "" if raw_value is None else raw_value.strip()
                if not value:
                    continue
                field = "row[%d].%s" % (row_number, clean_header)
                items.append(
                    EvidenceItem(
                        source_id=source_id,
                        page=1,
                        quote="%s=%s" % (clean_header, value),
                        field=field,
                        value=value,
                        confidence=1.0,
                    )
                )
        return items
    except csv.Error as exc:
        raise InputError("could not parse CSV %s: %s" % (source_id, exc)) from exc


def _parse_json(source_id: str, text: str) -> List[EvidenceItem]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(
            "could not parse JSON %s at line %d column %d"
            % (source_id, exc.lineno, exc.colno)
        ) from exc

    items = []
    for field, raw_value in _flatten_json(payload):
        value = _scalar_to_text(raw_value)
        items.append(
            EvidenceItem(
                source_id=source_id,
                page=1,
                quote="%s=%s" % (field, value),
                field=field,
                value=value,
                confidence=1.0,
            )
        )
    return items


def _flatten_json(value: Any, prefix: str = "") -> Iterable[Tuple[str, Any]]:
    if isinstance(value, dict):
        if not value and prefix:
            yield prefix, {}
        for key in sorted(value):
            child_prefix = "%s.%s" % (prefix, key) if prefix else str(key)
            yield from _flatten_json(value[key], child_prefix)
    elif isinstance(value, list):
        if not value and prefix:
            yield prefix, []
        for index, item in enumerate(value):
            child_prefix = "%s[%d]" % (prefix, index) if prefix else "[%d]" % index
            yield from _flatten_json(item, child_prefix)
    else:
        yield prefix or "$", value


def _parse_pdf(path: Path, source_id: str) -> List[EvidenceItem]:
    try:
        pypdf = import_module("pypdf")
    except ModuleNotFoundError as exc:
        raise OptionalDependencyError(
            "PDF input requires the optional dependency; install with "
            "`python -m pip install 'regulated-workflow-demo[pdf]'`"
        ) from exc

    try:
        reader = pypdf.PdfReader(str(path))
        items = []
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            items.extend(_parse_text(source_id, page_text, page=page_number))
        return items
    except Exception as exc:
        raise InputError("could not parse PDF %s: %s" % (source_id, exc)) from exc


def _deduplicate_fields(items: Sequence[EvidenceItem]) -> List[EvidenceItem]:
    counts: Dict[str, int] = {}
    used = set()
    result = []
    for item in items:
        occurrence = counts.get(item.field, 0) + 1
        counts[item.field] = occurrence
        candidate = item.field if occurrence == 1 else "%s[%d]" % (item.field, occurrence)
        while candidate in used:
            occurrence += 1
            counts[item.field] = occurrence
            candidate = "%s[%d]" % (item.field, occurrence)
        used.add(candidate)
        if candidate == item.field:
            result.append(item)
            continue
        result.append(
            EvidenceItem(
                source_id=item.source_id,
                page=item.page,
                quote=item.quote,
                field=candidate,
                value=item.value,
                confidence=item.confidence,
                review_status=item.review_status,
            )
        )
    return result


def _clean_markdown(value: str) -> str:
    return value.strip().strip("*`").strip()


def _scalar_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
