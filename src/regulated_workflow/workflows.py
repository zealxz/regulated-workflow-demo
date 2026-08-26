from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .errors import InputError
from .llm import OpenAICompatibleAdapter
from .models import ChangeItem, EvidenceItem
from .output import write_csv, write_json, write_jsonl, write_text
from .readers import ParsedDocument, read_documents


_HIGH_RISK_TERMS = (
    "approval",
    "authorized",
    "prohibited",
    "retention",
    "limit",
    "threshold",
    "effective",
    "required",
    "must",
    "shall",
    "expiry",
    "compliance",
    "审批",
    "批准",
    "禁止",
    "保留",
    "阈值",
    "上限",
    "生效",
    "必须",
    "到期",
    "合规",
)
_OUTPUT_NAMES = {
    "evidence.json",
    "changes.json",
    "review_queue.csv",
    "summary.md",
    "audit.jsonl",
    "llm_draft.md",
}


def run_extract(
    input_path: Path, output_dir: Path, llm_summary: bool = False
) -> Sequence[Path]:
    input_path = input_path.expanduser()
    output_dir = output_dir.expanduser()
    _validate_output_location((input_path,), output_dir)

    started_at = _utc_now()
    documents = read_documents(input_path, exclude_paths=(output_dir,))
    evidence = _collect_evidence(documents)
    review_rows = [_evidence_review_row(item) for item in evidence]
    summary = _extract_summary(documents, evidence)
    audit = _audit_records(
        mode="extract",
        started_at=started_at,
        inputs={"input": str(input_path)},
        documents=[("input", document) for document in documents],
        evidence_count=len(evidence),
        change_count=0,
        llm_summary=llm_summary,
    )
    draft = _optional_llm_draft(
        enabled=llm_summary,
        context=(
            "Workflow: extract\nDocuments: %d\nEvidence items pending review: %d"
            % (len(documents), len(evidence))
        ),
    )
    return _write_outputs(
        output_dir=output_dir,
        evidence=evidence,
        changes=(),
        review_rows=review_rows,
        summary=summary,
        audit=audit,
        llm_draft=draft,
    )


def run_diff(
    old_path: Path,
    new_path: Path,
    output_dir: Path,
    llm_summary: bool = False,
) -> Sequence[Path]:
    old_path = old_path.expanduser()
    new_path = new_path.expanduser()
    output_dir = output_dir.expanduser()
    if old_path.resolve() == new_path.resolve():
        raise InputError("old and new inputs must be different paths")
    _validate_output_location((old_path, new_path), output_dir)

    started_at = _utc_now()
    original_old_documents = read_documents(old_path, exclude_paths=(output_dir,))
    original_new_documents = read_documents(new_path, exclude_paths=(output_dir,))
    old_documents, new_documents = _align_single_file_sources(
        old_path,
        new_path,
        original_old_documents,
        original_new_documents,
    )
    old_evidence = _collect_evidence(old_documents)
    new_evidence = _collect_evidence(new_documents)
    changes = compare_evidence(old_evidence, new_evidence)
    review_rows = [_change_review_row(item) for item in changes]
    summary = _diff_summary(old_documents, new_documents, new_evidence, changes)
    risk_counts = Counter(change.risk_level for change in changes)
    audit = _audit_records(
        mode="diff",
        started_at=started_at,
        inputs={"old": str(old_path), "new": str(new_path)},
        documents=([("old", document) for document in original_old_documents]
                   + [("new", document) for document in original_new_documents]),
        evidence_count=len(new_evidence),
        change_count=len(changes),
        llm_summary=llm_summary,
    )
    draft = _optional_llm_draft(
        enabled=llm_summary,
        context=(
            "Workflow: diff\nOld documents: %d\nNew documents: %d\n"
            "Changes pending review: %d\nHigh risk: %d\nMedium risk: %d\nLow risk: %d"
            % (
                len(old_documents),
                len(new_documents),
                len(changes),
                risk_counts["high"],
                risk_counts["medium"],
                risk_counts["low"],
            )
        ),
    )
    return _write_outputs(
        output_dir=output_dir,
        evidence=new_evidence,
        changes=changes,
        review_rows=review_rows,
        summary=summary,
        audit=audit,
        llm_draft=draft,
    )


def compare_evidence(
    old_evidence: Sequence[EvidenceItem], new_evidence: Sequence[EvidenceItem]
) -> List[ChangeItem]:
    old_index = _evidence_index(old_evidence)
    new_index = _evidence_index(new_evidence)
    changes = []
    for source_id, field in sorted(set(old_index) | set(new_index)):
        old_item = old_index.get((source_id, field))
        new_item = new_index.get((source_id, field))
        old_value = old_item.value if old_item else ""
        new_value = new_item.value if new_item else ""
        if old_item and new_item and old_value == new_value:
            continue

        if old_item is None:
            change_kind = "added"
            rationale = "Field was added; confirm the new requirement and its source."
        elif new_item is None:
            change_kind = "removed"
            rationale = "Field was removed; confirm the omission is intentional."
        else:
            change_kind = "modified"
            rationale = "Value changed; confirm the revised value against the source."

        qualified_field = "%s::%s" % (source_id, field)
        changes.append(
            ChangeItem(
                field=qualified_field,
                old_value=old_value,
                new_value=new_value,
                risk_level=_risk_level(qualified_field, change_kind),
                rationale=rationale,
            )
        )
    return changes


def _evidence_index(
    evidence: Sequence[EvidenceItem],
) -> Mapping[Tuple[str, str], EvidenceItem]:
    index: Dict[Tuple[str, str], EvidenceItem] = {}
    for item in evidence:
        key = (item.source_id, item.field)
        if key in index:
            raise InputError("duplicate evidence key: %s::%s" % key)
        index[key] = item
    return index


def _risk_level(field: str, change_kind: str) -> str:
    normalized = field.casefold()
    if change_kind == "removed":
        return "high"
    if any(term in normalized for term in _HIGH_RISK_TERMS):
        return "high"
    if change_kind == "modified":
        return "medium"
    return "low"


def _collect_evidence(documents: Sequence[ParsedDocument]) -> List[EvidenceItem]:
    return [item for document in documents for item in document.evidence]


def _align_single_file_sources(
    old_path: Path,
    new_path: Path,
    old_documents: Sequence[ParsedDocument],
    new_documents: Sequence[ParsedDocument],
) -> Tuple[Sequence[ParsedDocument], Sequence[ParsedDocument]]:
    """Give two direct-file versions one shared, readable comparison identity."""
    if not (old_path.is_file() and new_path.is_file()):
        return old_documents, new_documents
    if len(old_documents) != 1 or len(new_documents) != 1:
        raise InputError("direct file inputs must each resolve to exactly one document")

    old_source = old_documents[0].source_id
    new_source = new_documents[0].source_id
    source_label = (
        old_source if old_source == new_source else "%s -> %s" % (old_source, new_source)
    )
    return (
        (_relabel_document(old_documents[0], source_label),),
        (_relabel_document(new_documents[0], source_label),),
    )


def _relabel_document(document: ParsedDocument, source_label: str) -> ParsedDocument:
    evidence = tuple(replace(item, source_id=source_label) for item in document.evidence)
    return replace(document, source_id=source_label, evidence=evidence)


def _extract_summary(
    documents: Sequence[ParsedDocument], evidence: Sequence[EvidenceItem]
) -> str:
    low_confidence = sum(item.confidence < 0.8 for item in evidence)
    return "\n".join(
        [
            "# Extraction Review Summary",
            "",
            "- Documents processed: %d" % len(documents),
            "- Evidence items: %d" % len(evidence),
            "- Items below 0.80 confidence: %d" % low_confidence,
            "- Review status: all items pending human review",
            "",
            "## Source Files",
            "",
        ]
        + ["- `%s`" % document.source_id for document in documents]
        + [
            "",
            "## Approval Boundary",
            "",
            "These outputs are extraction aids, not compliance conclusions. "
            "A human reviewer must verify source quotes and approve any downstream use.",
        ]
    )


def _diff_summary(
    old_documents: Sequence[ParsedDocument],
    new_documents: Sequence[ParsedDocument],
    new_evidence: Sequence[EvidenceItem],
    changes: Sequence[ChangeItem],
) -> str:
    risk_counts = Counter(change.risk_level for change in changes)
    return "\n".join(
        [
            "# Version Change Review Summary",
            "",
            "- Old documents processed: %d" % len(old_documents),
            "- New documents processed: %d" % len(new_documents),
            "- Current evidence items: %d" % len(new_evidence),
            "- Changes pending review: %d" % len(changes),
            "- High-risk review flags: %d" % risk_counts["high"],
            "- Medium-risk review flags: %d" % risk_counts["medium"],
            "- Low-risk review flags: %d" % risk_counts["low"],
            "",
            "## Approval Boundary",
            "",
            "Risk levels are deterministic review-priority hints, not regulatory judgments. "
            "A human reviewer must verify every change before approval or downstream action.",
        ]
    )


def _evidence_review_row(item: EvidenceItem) -> Dict[str, Any]:
    return {
        "record_type": "evidence",
        "source_id": item.source_id,
        "field": item.field,
        "value": item.value,
        "old_value": "",
        "new_value": "",
        "confidence": "%.2f" % item.confidence,
        "risk_level": "",
        "reason": "Verify the source quote and extracted value.",
        "review_status": item.review_status,
    }


def _change_review_row(item: ChangeItem) -> Dict[str, Any]:
    source_id, _, field = item.field.partition("::")
    return {
        "record_type": "change",
        "source_id": source_id,
        "field": field,
        "value": "",
        "old_value": item.old_value,
        "new_value": item.new_value,
        "confidence": "",
        "risk_level": item.risk_level,
        "reason": item.rationale,
        "review_status": item.review_status,
    }


def _audit_records(
    mode: str,
    started_at: str,
    inputs: Mapping[str, str],
    documents: Sequence[Tuple[str, ParsedDocument]],
    evidence_count: int,
    change_count: int,
    llm_summary: bool,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = [
        {
            "event": "run_started",
            "timestamp": started_at,
            "mode": mode,
            "inputs": dict(inputs),
            "network_mode": "explicit-counts-only" if llm_summary else "offline",
        }
    ]
    records.extend(
        {
            "event": "document_parsed",
            "timestamp": started_at,
            "input_role": input_role,
            "source_id": document.source_id,
            "format": document.format,
            "sha256": document.sha256,
            "byte_size": document.byte_size,
            "evidence_count": len(document.evidence),
        }
        for input_role, document in documents
    )
    records.append(
        {
            "event": "run_completed",
            "timestamp": _utc_now(),
            "mode": mode,
            "document_count": len(documents),
            "evidence_count": evidence_count,
            "change_count": change_count,
            "review_required": True,
        }
    )
    return records


def _optional_llm_draft(enabled: bool, context: str) -> Optional[str]:
    if not enabled:
        return None
    adapter = OpenAICompatibleAdapter.from_env()
    return adapter.draft_summary(context)


def _write_outputs(
    output_dir: Path,
    evidence: Sequence[EvidenceItem],
    changes: Sequence[ChangeItem],
    review_rows: Sequence[Dict[str, Any]],
    summary: str,
    audit: Sequence[Dict[str, Any]],
    llm_draft: Optional[str],
) -> Sequence[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        output_dir / "evidence.json",
        output_dir / "changes.json",
        output_dir / "review_queue.csv",
        output_dir / "summary.md",
        output_dir / "audit.jsonl",
    ]
    write_json(paths[0], [item.to_dict() for item in evidence])
    write_json(paths[1], [item.to_dict() for item in changes])
    write_csv(paths[2], review_rows)
    write_text(paths[3], summary)
    write_jsonl(paths[4], audit)
    if llm_draft is not None:
        llm_path = output_dir / "llm_draft.md"
        write_text(
            llm_path,
            "# Unreviewed Remote Draft\n\n%s\n\nHuman review is required." % llm_draft,
        )
        paths.append(llm_path)
    return tuple(paths)


def _validate_output_location(inputs: Iterable[Path], output_dir: Path) -> None:
    resolved_output = output_dir.resolve()
    for input_path in inputs:
        resolved_input = input_path.resolve()
        if resolved_input == resolved_output:
            raise InputError("output directory must not be the input path")
        if resolved_input.is_file() and resolved_input.parent == resolved_output:
            if resolved_input.name in _OUTPUT_NAMES:
                raise InputError("output would overwrite input file: %s" % resolved_input)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
