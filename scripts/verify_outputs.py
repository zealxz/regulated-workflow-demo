#!/usr/bin/env python3
"""Verify canonical records, review defaults, audit events, and XLSX structure."""

from __future__ import annotations

import argparse
import csv
import json
import math
import posixpath
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


REQUIRED_REVIEW_STATUSES = {"pending", "approved", "rejected"}
REQUIRED_RISK_LEVELS = {"low", "medium", "high"}
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
NS = {"m": MAIN_NS, "pr": PACKAGE_REL_NS, "ct": CONTENT_TYPES_NS}
RID_ATTRIBUTE = "{%s}id" % OFFICE_REL_NS
WORKBOOK_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
WORKSHEET_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
TABLE_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extract_dir", type=Path)
    parser.add_argument("diff_dir", type=Path)
    parser.add_argument("--skip-workbooks", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise AssertionError("%s must contain a JSON array of objects" % path)
    return payload


def check_required(item: dict[str, Any], names: set[str], path: Path) -> None:
    missing = names.difference(item)
    if missing:
        raise AssertionError("%s item is missing fields: %s" % (path, sorted(missing)))


def check_review_csv(path: Path, expected_rows: int) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != expected_rows:
        raise AssertionError("%s contains %d rows; expected %d" % (path, len(rows), expected_rows))
    if any(row.get("review_status") != "pending" for row in rows):
        raise AssertionError("%s must begin with every review_status pending" % path)


def check_audit(path: Path, expected_mode: str) -> int:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    names = {event.get("event") for event in events}
    if not {"run_started", "document_parsed", "run_completed"}.issubset(names):
        raise AssertionError("%s lacks required lifecycle events" % path)
    started = next(event for event in events if event.get("event") == "run_started")
    if started.get("mode") != expected_mode or started.get("network_mode") != "offline":
        raise AssertionError("%s must record an offline %s run" % (path, expected_mode))
    return len(events)


def _read_xml(archive: zipfile.ZipFile, member: str, path: Path) -> ET.Element:
    try:
        payload = archive.read(member)
    except KeyError as exc:
        raise AssertionError("%s is missing XLSX part %s" % (path, member)) from exc
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise AssertionError("%s contains invalid XML in %s: %s" % (path, member, exc)) from exc


def _relationships_part(source_part: str) -> str:
    directory = posixpath.dirname(source_part)
    name = posixpath.basename(source_part)
    return posixpath.join(directory, "_rels", name + ".rels")


def _relationship_map(root: ET.Element, path: Path, part: str) -> dict[str, dict[str, str]]:
    relationships: dict[str, dict[str, str]] = {}
    for element in root.findall("pr:Relationship", NS):
        relation_id = element.get("Id")
        if not relation_id or relation_id in relationships:
            raise AssertionError("%s has a missing or duplicate relationship Id in %s" % (path, part))
        relationships[relation_id] = dict(element.attrib)
    return relationships


def _resolve_target(source_part: str, target: str, path: Path) -> str:
    if not target or "\\" in target:
        raise AssertionError("%s has an invalid relationship target %r" % (path, target))
    if target.startswith("/"):
        resolved = posixpath.normpath(target.lstrip("/"))
    else:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))
    if resolved in {"", ".", ".."} or resolved.startswith("../"):
        raise AssertionError("%s has an out-of-package relationship target %r" % (path, target))
    return resolved


def _require_internal_targets(
    relationships: dict[str, dict[str, str]],
    source_part: str,
    members: set[str],
    path: Path,
) -> None:
    for relationship in relationships.values():
        if relationship.get("TargetMode") == "External":
            continue
        target = _resolve_target(source_part, relationship.get("Target", ""), path)
        if target not in members:
            raise AssertionError("%s relationship from %s is missing target %s" % (path, source_part, target))


def _content_type_for(
    part: str,
    overrides: dict[str, str],
    defaults: dict[str, str],
) -> str | None:
    extension = posixpath.splitext(part)[1].lstrip(".")
    return overrides.get(part) or defaults.get(extension)


def _formula_contract(kind: str, items: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, float]]:
    last_row = len(items) + 4
    if kind == "evidence":
        confidences = []
        for item in items:
            try:
                confidence = float(item["confidence"])
            except (TypeError, ValueError) as exc:
                raise AssertionError("evidence confidence must be numeric") from exc
            if not math.isfinite(confidence):
                raise AssertionError("evidence confidence must be finite")
            confidences.append(confidence)
        average = sum(confidences) / len(confidences)
        formulas = {
            "B5": "COUNTA('Evidence'!$A$5:$A$%d)" % last_row,
            "B6": 'COUNTIF(\'Evidence\'!$H$5:$H$%d,"pending")' % last_row,
            "B7": 'COUNTIF(\'Evidence\'!$H$5:$H$%d,"approved")' % last_row,
            "B8": 'COUNTIF(\'Evidence\'!$H$5:$H$%d,"rejected")' % last_row,
            "B9": "IFERROR(AVERAGE('Evidence'!$G$5:$G$%d),0)" % last_row,
        }
        values = {"B5": len(items), "B6": len(items), "B7": 0, "B8": 0, "B9": average}
        return formulas, values

    risk_counts = {
        risk: sum(item["risk_level"] == risk for item in items)
        for risk in REQUIRED_RISK_LEVELS
    }
    formulas = {
        "B5": "COUNTA('Changes'!$A$5:$A$%d)" % last_row,
        "B6": 'COUNTIF(\'Changes\'!$E$5:$E$%d,"high")' % last_row,
        "B7": 'COUNTIF(\'Changes\'!$E$5:$E$%d,"medium")' % last_row,
        "B8": 'COUNTIF(\'Changes\'!$E$5:$E$%d,"low")' % last_row,
        "B9": 'COUNTIF(\'Changes\'!$H$5:$H$%d,"pending")' % last_row,
        "E5": "B6",
        "E6": "B7",
        "E7": "B8",
    }
    values = {
        "B5": len(items),
        "B6": risk_counts["high"],
        "B7": risk_counts["medium"],
        "B8": risk_counts["low"],
        "B9": len(items),
        "E5": risk_counts["high"],
        "E6": risk_counts["medium"],
        "E7": risk_counts["low"],
    }
    return formulas, values


def _workbook_contract(
    kind: str,
    items: list[dict[str, Any]],
    audit_count: int,
) -> dict[str, Any]:
    last_row = len(items) + 4
    audit_last_row = max(1, audit_count) + 4
    formulas, formula_values = _formula_contract(kind, items)
    status_formula = '"pending,approved,rejected"'
    if kind == "evidence":
        return {
            "sheets": {"Summary", "Evidence", "Review Queue", "Audit"},
            "tables": {
                "Evidence": {"EvidenceItemsTable": "A4:H%d" % last_row},
                "Review Queue": {"EvidenceReviewTable": "A4:J%d" % last_row},
                "Audit": {"AuditEventsTable": "A4:G%d" % audit_last_row},
            },
            "validations": {
                "Evidence": {("list", "H5:H%d" % last_row, status_formula)},
                "Review Queue": {("list", "I5:I%d" % last_row, status_formula)},
            },
            "bottom_cells": {
                "Evidence": "H%d" % last_row,
                "Review Queue": "I%d" % last_row,
                "Audit": "B%d" % audit_last_row,
            },
            "formulas": formulas,
            "formula_values": formula_values,
        }
    return {
        "sheets": {"Summary", "Changes", "Review Queue", "Audit"},
        "tables": {
            "Changes": {"DocumentChangesTable": "A4:H%d" % last_row},
            "Review Queue": {"ChangeReviewTable": "A4:J%d" % last_row},
            "Audit": {"AuditEventsTable": "A4:G%d" % audit_last_row},
        },
        "validations": {
            "Changes": {
                ("list", "E5:E%d" % last_row, '"low,medium,high"'),
                ("list", "H5:H%d" % last_row, status_formula),
            },
            "Review Queue": {("list", "I5:I%d" % last_row, status_formula)},
        },
        "bottom_cells": {
            "Changes": "H%d" % last_row,
            "Review Queue": "I%d" % last_row,
            "Audit": "B%d" % audit_last_row,
        },
        "formulas": formulas,
        "formula_values": formula_values,
    }


def _validate_summary(
    worksheet: ET.Element,
    formulas: dict[str, str],
    expected_values: dict[str, float],
    path: Path,
) -> None:
    cells = {cell.get("r"): cell for cell in worksheet.findall(".//m:c", NS)}
    for address, expected_formula in formulas.items():
        cell = cells.get(address)
        if cell is None:
            raise AssertionError("%s Summary is missing formula cell %s" % (path, address))
        formula = cell.find("m:f", NS)
        if formula is None or formula.text != expected_formula:
            raise AssertionError(
                "%s Summary %s formula is %r; expected %r"
                % (path, address, None if formula is None else formula.text, expected_formula)
            )
        value = cell.find("m:v", NS)
        if cell.get("t") == "e" or value is None or value.text is None:
            raise AssertionError("%s Summary %s has no numeric cached value" % (path, address))
        try:
            actual_value = float(value.text)
        except ValueError as exc:
            raise AssertionError("%s Summary %s cached value is not numeric" % (path, address)) from exc
        expected_value = float(expected_values[address])
        if not math.isfinite(actual_value) or not math.isclose(
            actual_value, expected_value, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise AssertionError(
                "%s Summary %s value is %r; expected %r"
                % (path, address, actual_value, expected_value)
            )


def _validation_set(worksheet: ET.Element, path: Path, sheet_name: str) -> set[tuple[str, str, str]]:
    containers = worksheet.findall("m:dataValidations", NS)
    if len(containers) > 1:
        raise AssertionError("%s sheet %s has multiple dataValidations containers" % (path, sheet_name))
    validations = worksheet.findall(".//m:dataValidation", NS)
    if containers and int(containers[0].get("count", "-1")) != len(validations):
        raise AssertionError("%s sheet %s has an incorrect dataValidation count" % (path, sheet_name))
    result = set()
    for validation in validations:
        formula = validation.find("m:formula1", NS)
        result.add((validation.get("type", ""), validation.get("sqref", ""), formula.text or "" if formula is not None else ""))
    return result


def _validate_tables(
    archive: zipfile.ZipFile,
    members: set[str],
    content_type_overrides: dict[str, str],
    content_type_defaults: dict[str, str],
    sheet_part: str,
    worksheet: ET.Element,
    expected_tables: dict[str, str],
    path: Path,
) -> None:
    table_parts = worksheet.findall(".//m:tablePart", NS)
    containers = worksheet.findall("m:tableParts", NS)
    if len(containers) > 1 or (containers and int(containers[0].get("count", "-1")) != len(table_parts)):
        raise AssertionError("%s has an invalid tableParts count in %s" % (path, sheet_part))
    if len(table_parts) != len(expected_tables):
        raise AssertionError(
            "%s has %d tables in %s; expected %d"
            % (path, len(table_parts), sheet_part, len(expected_tables))
        )
    if not table_parts:
        return

    relationships_part = _relationships_part(sheet_part)
    relationship_root = _read_xml(archive, relationships_part, path)
    relationships = _relationship_map(relationship_root, path, relationships_part)
    _require_internal_targets(relationships, sheet_part, members, path)
    actual_tables: dict[str, str] = {}
    for table_part in table_parts:
        relation_id = table_part.get(RID_ATTRIBUTE)
        relationship = relationships.get(relation_id or "")
        if relationship is None or not relationship.get("Type", "").endswith("/table"):
            raise AssertionError("%s has an invalid table relationship in %s" % (path, sheet_part))
        target = _resolve_target(sheet_part, relationship.get("Target", ""), path)
        if _content_type_for(target, content_type_overrides, content_type_defaults) != TABLE_CONTENT_TYPE:
            raise AssertionError("%s table part %s has the wrong content type" % (path, target))
        table = _read_xml(archive, target, path)
        name = table.get("name")
        reference = table.get("ref")
        if not name or name in actual_tables:
            raise AssertionError("%s has a missing or duplicate table name in %s" % (path, target))
        actual_tables[name] = reference or ""
    if actual_tables != expected_tables:
        raise AssertionError("%s tables in %s are %r; expected %r" % (path, sheet_part, actual_tables, expected_tables))


def check_workbook(
    path: Path,
    kind: str,
    items: list[dict[str, Any]],
    audit_count: int,
) -> None:
    if not zipfile.is_zipfile(path):
        raise AssertionError("%s is not a valid XLSX ZIP container" % path)
    contract = _workbook_contract(kind, items, audit_count)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise AssertionError("%s contains duplicate ZIP member names" % path)
        corrupt_member = archive.testzip()
        if corrupt_member is not None:
            raise AssertionError("%s has a corrupt ZIP member: %s" % (path, corrupt_member))
        members = set(names)

        content_types = _read_xml(archive, "[Content_Types].xml", path)
        content_type_overrides = {
            override.get("PartName", "").lstrip("/"): override.get("ContentType", "")
            for override in content_types.findall("ct:Override", NS)
        }
        content_type_defaults = {
            default.get("Extension", ""): default.get("ContentType", "")
            for default in content_types.findall("ct:Default", NS)
        }
        package_relationships_root = _read_xml(archive, "_rels/.rels", path)
        package_relationships = _relationship_map(package_relationships_root, path, "_rels/.rels")
        _require_internal_targets(package_relationships, "", members, path)
        office_documents = [
            relationship
            for relationship in package_relationships.values()
            if relationship.get("Type", "").endswith("/officeDocument")
            and relationship.get("TargetMode") != "External"
        ]
        if len(office_documents) != 1:
            raise AssertionError("%s must contain exactly one internal officeDocument relationship" % path)
        workbook_part = _resolve_target("", office_documents[0].get("Target", ""), path)
        if _content_type_for(workbook_part, content_type_overrides, content_type_defaults) != WORKBOOK_CONTENT_TYPE:
            raise AssertionError("%s workbook part has the wrong content type" % path)

        workbook = _read_xml(archive, workbook_part, path)
        workbook_relationships_part = _relationships_part(workbook_part)
        workbook_relationships_root = _read_xml(archive, workbook_relationships_part, path)
        workbook_relationships = _relationship_map(
            workbook_relationships_root, path, workbook_relationships_part
        )
        _require_internal_targets(workbook_relationships, workbook_part, members, path)

        sheet_elements = workbook.findall("m:sheets/m:sheet", NS)
        actual_sheet_names = {sheet.get("name", "") for sheet in sheet_elements}
        if actual_sheet_names != contract["sheets"] or len(sheet_elements) != len(contract["sheets"]):
            raise AssertionError(
                "%s sheets are %r; expected %r" % (path, actual_sheet_names, contract["sheets"])
            )

        for sheet in sheet_elements:
            sheet_name = sheet.get("name", "")
            relation_id = sheet.get(RID_ATTRIBUTE)
            relationship = workbook_relationships.get(relation_id or "")
            if relationship is None or not relationship.get("Type", "").endswith("/worksheet"):
                raise AssertionError("%s sheet %s has an invalid worksheet relationship" % (path, sheet_name))
            sheet_part = _resolve_target(workbook_part, relationship.get("Target", ""), path)
            if _content_type_for(sheet_part, content_type_overrides, content_type_defaults) != WORKSHEET_CONTENT_TYPE:
                raise AssertionError("%s worksheet %s has the wrong content type" % (path, sheet_part))
            worksheet = _read_xml(archive, sheet_part, path)
            if worksheet.tag != "{%s}worksheet" % MAIN_NS:
                raise AssertionError("%s part %s is not a worksheet" % (path, sheet_part))

            relationships_part = _relationships_part(sheet_part)
            if relationships_part in members:
                relationship_root = _read_xml(archive, relationships_part, path)
                relationships = _relationship_map(relationship_root, path, relationships_part)
                _require_internal_targets(relationships, sheet_part, members, path)

            expected_validations = contract["validations"].get(sheet_name, set())
            actual_validations = _validation_set(worksheet, path, sheet_name)
            if actual_validations != expected_validations:
                raise AssertionError(
                    "%s validations in %s are %r; expected %r"
                    % (path, sheet_name, actual_validations, expected_validations)
                )
            _validate_tables(
                archive,
                members,
                content_type_overrides,
                content_type_defaults,
                sheet_part,
                worksheet,
                contract["tables"].get(sheet_name, {}),
                path,
            )
            bottom_cell = contract["bottom_cells"].get(sheet_name)
            if bottom_cell and worksheet.find('.//m:c[@r="%s"]' % bottom_cell, NS) is None:
                raise AssertionError("%s sheet %s is missing final data cell %s" % (path, sheet_name, bottom_cell))
            if sheet_name == "Summary":
                _validate_summary(
                    worksheet,
                    contract["formulas"],
                    contract["formula_values"],
                    path,
                )


def main() -> int:
    args = parse_args()
    extract_required = {
        "evidence.json",
        "changes.json",
        "review_queue.csv",
        "summary.md",
        "audit.jsonl",
    }
    diff_required = set(extract_required)
    if not args.skip_workbooks:
        extract_required.add("evidence.xlsx")
        diff_required.add("changes.xlsx")
    for directory, names in ((args.extract_dir, extract_required), (args.diff_dir, diff_required)):
        missing = [name for name in sorted(names) if not (directory / name).is_file()]
        if missing:
            raise AssertionError("%s is missing: %s" % (directory, missing))

    evidence_path = args.extract_dir / "evidence.json"
    evidence = load_json(evidence_path)
    if not evidence:
        raise AssertionError("extract evidence must not be empty")
    for item in evidence:
        check_required(
            item,
            {"source_id", "page", "quote", "field", "value", "confidence", "review_status"},
            evidence_path,
        )
        if item["review_status"] not in REQUIRED_REVIEW_STATUSES:
            raise AssertionError("unsupported evidence review status")
        if item["review_status"] != "pending":
            raise AssertionError("demo evidence must begin pending")

    changes_path = args.diff_dir / "changes.json"
    changes = load_json(changes_path)
    if not changes:
        raise AssertionError("diff changes must not be empty")
    for item in changes:
        check_required(
            item,
            {"field", "old_value", "new_value", "risk_level", "rationale", "review_status"},
            changes_path,
        )
        if item["risk_level"] not in REQUIRED_RISK_LEVELS:
            raise AssertionError("unsupported risk level")
        if item["review_status"] != "pending":
            raise AssertionError("demo changes must begin pending")

    check_review_csv(args.extract_dir / "review_queue.csv", len(evidence))
    check_review_csv(args.diff_dir / "review_queue.csv", len(changes))
    extract_audit_count = check_audit(args.extract_dir / "audit.jsonl", "extract")
    diff_audit_count = check_audit(args.diff_dir / "audit.jsonl", "diff")
    if not args.skip_workbooks:
        check_workbook(
            args.extract_dir / "evidence.xlsx",
            "evidence",
            evidence,
            extract_audit_count,
        )
        check_workbook(
            args.diff_dir / "changes.xlsx",
            "changes",
            changes,
            diff_audit_count,
        )

    print(
        json.dumps(
            {
                "ok": True,
                "evidence_items": len(evidence),
                "change_items": len(changes),
                "workbooks_checked": not args.skip_workbooks,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
