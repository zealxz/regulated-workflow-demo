import fs from "node:fs/promises";
import path from "node:path";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const COLORS = {
  navy: "#16324F",
  teal: "#0F766E",
  paleTeal: "#DDF4F0",
  paleBlue: "#EAF1F8",
  paleAmber: "#FFF4D6",
  paleRed: "#FDE8E7",
  paleGreen: "#E7F5EC",
  gray: "#5F6B76",
  lightGray: "#E2E8F0",
  white: "#FFFFFF",
};

const MAX_PREVIEW_DATA_ROWS = 30;

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (!value.startsWith("--")) continue;
    const key = value.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      parsed[key] = true;
    } else {
      parsed[key] = next;
      index += 1;
    }
  }
  return parsed;
}

function requireArgs(args, names) {
  const missing = names.filter((name) => !args[name]);
  if (missing.length) {
    throw new Error(`Missing required arguments: ${missing.map((name) => `--${name}`).join(", ")}`);
  }
}

async function readJson(filePath, kind) {
  const payload = JSON.parse(await fs.readFile(filePath, "utf8"));
  if (Array.isArray(payload)) return payload;
  const candidates = kind === "evidence"
    ? [payload.evidence, payload.items, payload.records]
    : [payload.changes, payload.items, payload.records];
  const items = candidates.find(Array.isArray);
  if (!items) throw new Error(`${filePath} does not contain an item array`);
  return items;
}

async function readAudit(filePath) {
  if (!filePath) return [];
  const text = await fs.readFile(filePath, "utf8");
  return text.split(/\r?\n/).filter(Boolean).map((line, index) => {
    try {
      return JSON.parse(line);
    } catch (error) {
      throw new Error(`Invalid audit JSONL at line ${index + 1}: ${error.message}`);
    }
  });
}

function setTitle(sheet, title, subtitle, width) {
  sheet.showGridLines = false;
  sheet.getRange(`A1:${width}1`).merge();
  sheet.getRange("A1").values = [[title]];
  sheet.getRange("A1").format = {
    fill: COLORS.navy,
    font: { color: COLORS.white, bold: true, size: 18 },
    verticalAlignment: "center",
  };
  sheet.getRange("A1").format.rowHeight = 34;
  sheet.getRange(`A2:${width}2`).merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange("A2").format = {
    fill: COLORS.paleBlue,
    font: { color: COLORS.gray, italic: true, size: 10 },
    wrapText: true,
  };
  sheet.getRange("A2").format.rowHeight = 30;
}

function styleHeader(range) {
  range.format = {
    fill: COLORS.teal,
    font: { color: COLORS.white, bold: true },
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: COLORS.teal },
  };
  range.format.rowHeight = 28;
}

function styleData(range) {
  range.format = {
    font: { color: "#17212B", size: 10 },
    verticalAlignment: "top",
    wrapText: true,
    borders: {
      insideHorizontal: { style: "thin", color: COLORS.lightGray },
      bottom: { style: "thin", color: COLORS.lightGray },
    },
  };
}

function value(item, ...keys) {
  for (const key of keys) {
    if (item[key] !== undefined && item[key] !== null) return item[key];
  }
  return "";
}

function excelSafe(rawValue) {
  const textValue = String(rawValue ?? "");
  const formulaCandidate = textValue.replace(/^[\s\u00A0\uFEFF]+/u, "");
  const beginsWithControl = /^[\t\r\n]/u.test(textValue);
  return beginsWithControl || /^[=+\-@]/u.test(formulaCandidate) ? `'${textValue}` : textValue;
}

function locatorFor(item) {
  const explicit = value(item, "locator", "source_locator");
  if (explicit !== "") return excelSafe(explicit);
  const page = value(item, "page");
  return page === "" ? "" : `page ${page}`;
}

function splitChangeField(item) {
  const explicitSource = value(item, "source_id");
  const rawField = String(value(item, "field"));
  if (explicitSource !== "") return [excelSafe(explicitSource), excelSafe(rawField)];
  const separator = rawField.indexOf("::");
  if (separator < 0) return ["", excelSafe(rawField)];
  return [excelSafe(rawField.slice(0, separator)), excelSafe(rawField.slice(separator + 2))];
}

function auditCount(event) {
  if (event.event === "run_completed" && Number(event.change_count || 0) > 0) {
    return Number(event.change_count);
  }
  return Number(
    event.record_count
      ?? event.count
      ?? event.evidence_count
      ?? event.document_count
      ?? event.change_count
      ?? 0,
  );
}

function auditDetails(event) {
  const details = {};
  for (const key of ["network_mode", "input_role", "format", "byte_size", "review_required"]) {
    if (event[key] !== undefined) details[key] = event[key];
  }
  if (event.details !== undefined) details.details = event.details;
  return excelSafe(JSON.stringify(details));
}

function addAuditSheet(workbook, auditItems) {
  const sheet = workbook.worksheets.add("Audit");
  setTitle(sheet, "Audit Trail", "Run metadata only. Credentials and full environment values are intentionally excluded.", "G");
  const headers = ["Timestamp", "Event", "Command", "Source ID", "Input Hash", "Record Count", "Details"];
  sheet.getRange("A4:G4").values = [headers];
  styleHeader(sheet.getRange("A4:G4"));
  const rows = (auditItems.length ? auditItems : [{ event: "no_audit_events" }]).map((event) => [
    excelSafe(value(event, "timestamp", "time", "created_at")),
    excelSafe(value(event, "event", "event_type", "action")),
    excelSafe(value(event, "command", "workflow", "mode")),
    excelSafe(value(event, "source_id", "source")),
    excelSafe(value(event, "input_hash", "sha256", "hash")),
    auditCount(event),
    auditDetails(event),
  ]);
  sheet.getRangeByIndexes(4, 0, rows.length, headers.length).values = rows;
  styleData(sheet.getRangeByIndexes(4, 0, rows.length, headers.length));
  sheet.getRange(`A5:A${rows.length + 4}`).format.numberFormat = "yyyy-mm-dd hh:mm";
  sheet.getRange(`F5:F${rows.length + 4}`).format.numberFormat = "#,##0";
  [21, 22, 18, 20, 34, 14, 60].forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, rows.length + 4, 1).format.columnWidth = width;
  });
  sheet.freezePanes.freezeRows(4);
  sheet.tables.add(`A4:G${rows.length + 4}`, true, "AuditEventsTable").style = "TableStyleMedium2";
  return sheet;
}

function addEvidenceWorkbook(items, auditItems) {
  const workbook = Workbook.create();
  const summary = workbook.worksheets.add("Summary");
  const evidence = workbook.worksheets.add("Evidence");
  const review = workbook.worksheets.add("Review Queue");
  addAuditSheet(workbook, auditItems);
  const evidenceLastRow = Math.max(5, items.length + 4);

  setTitle(summary, "Evidence Register", "Draft output for human review — not a compliance determination.", "H");
  summary.getRange("A4:B4").values = [["Metric", "Value"]];
  styleHeader(summary.getRange("A4:B4"));
  summary.getRange("A5:A9").values = [["Evidence items"], ["Pending review"], ["Approved"], ["Rejected"], ["Average confidence"]];
  summary.getRange("B5:B9").formulas = [[`=COUNTA('Evidence'!$A$5:$A$${evidenceLastRow})`], [`=COUNTIF('Evidence'!$H$5:$H$${evidenceLastRow},"pending")`], [`=COUNTIF('Evidence'!$H$5:$H$${evidenceLastRow},"approved")`], [`=COUNTIF('Evidence'!$H$5:$H$${evidenceLastRow},"rejected")`], [`=IFERROR(AVERAGE('Evidence'!$G$5:$G$${evidenceLastRow}),0)`]];
  summary.getRange("B5:B8").format.numberFormat = "#,##0";
  summary.getRange("B9").format.numberFormat = "0.0%";
  summary.getRange("A5:B9").format.borders = { preset: "outside", style: "thin", color: COLORS.lightGray };
  summary.getRange("A11:H11").merge();
  summary.getRange("A11").values = [["How to use: verify the quote and locator, choose a review status, and add a reviewer note before treating any row as approved."]];
  summary.getRange("A11").format = { fill: COLORS.paleAmber, font: { color: "#6B4F00", bold: true }, wrapText: true };
  summary.getRange("A11").format.rowHeight = 36;
  summary.getRange("A4:B9").format.columnWidth = 22;

  const headers = ["Source ID", "Source", "Locator", "Field", "Value", "Quote", "Confidence", "Review Status"];
  setTitle(evidence, "Evidence Items", "Canonical records derived from local sample inputs. Use the review status rather than formatting as the decision field.", "H");
  evidence.getRange("A4:H4").values = [headers];
  styleHeader(evidence.getRange("A4:H4"));
  const evidenceRows = items.map((item) => [
    excelSafe(value(item, "source_id")), excelSafe(value(item, "source_path", "source", "source_id")), locatorFor(item), excelSafe(value(item, "field")),
    excelSafe(value(item, "value")), excelSafe(value(item, "quote")), Number(value(item, "confidence") || 0), excelSafe(String(value(item, "review_status") || "pending").toLowerCase()),
  ]);
  const safeEvidenceRows = evidenceRows.length ? evidenceRows : [["", "", "", "", "", "", 0, "pending"]];
  evidence.getRangeByIndexes(4, 0, safeEvidenceRows.length, headers.length).values = safeEvidenceRows;
  styleData(evidence.getRangeByIndexes(4, 0, safeEvidenceRows.length, headers.length));
  evidence.getRange(`G5:G${safeEvidenceRows.length + 4}`).format.numberFormat = "0.0%";
  evidence.getRange(`H5:H${safeEvidenceRows.length + 4}`).dataValidation = { rule: { type: "list", values: ["pending", "approved", "rejected"] } };
  evidence.getRange(`H5:H${safeEvidenceRows.length + 4}`).conditionalFormats.add("containsText", { text: "pending", format: { fill: COLORS.paleAmber, font: { color: "#6B4F00" } } });
  evidence.getRange(`H5:H${safeEvidenceRows.length + 4}`).conditionalFormats.add("containsText", { text: "approved", format: { fill: COLORS.paleGreen, font: { color: "#155A32" } } });
  evidence.getRange(`H5:H${safeEvidenceRows.length + 4}`).conditionalFormats.add("containsText", { text: "rejected", format: { fill: COLORS.paleRed, font: { color: "#8A1C1C" } } });
  [20, 36, 18, 22, 30, 58, 14, 18].forEach((width, index) => evidence.getRangeByIndexes(0, index, safeEvidenceRows.length + 4, 1).format.columnWidth = width);
  evidence.freezePanes.freezeRows(4);
  evidence.tables.add(`A4:H${safeEvidenceRows.length + 4}`, true, "EvidenceItemsTable").style = "TableStyleMedium2";

  setTitle(review, "Human Review Queue", "Editable decisions are intentionally separate from extracted evidence. Every item begins as pending.", "J");
  const reviewHeaders = [...headers, "Reviewer Decision", "Reviewer Note"];
  review.getRange("A4:J4").values = [reviewHeaders];
  styleHeader(review.getRange("A4:J4"));
  const reviewRows = safeEvidenceRows.map((row) => [...row, "pending", ""]);
  review.getRangeByIndexes(4, 0, reviewRows.length, reviewHeaders.length).values = reviewRows;
  styleData(review.getRangeByIndexes(4, 0, reviewRows.length, reviewHeaders.length));
  review.getRange(`G5:G${reviewRows.length + 4}`).format.numberFormat = "0.0%";
  review.getRange(`I5:I${reviewRows.length + 4}`).dataValidation = { rule: { type: "list", values: ["pending", "approved", "rejected"] } };
  [20, 32, 16, 20, 26, 48, 12, 16, 18, 42].forEach((width, index) => review.getRangeByIndexes(0, index, reviewRows.length + 4, 1).format.columnWidth = width);
  review.freezePanes.freezeRows(4);
  review.tables.add(`A4:J${reviewRows.length + 4}`, true, "EvidenceReviewTable").style = "TableStyleMedium2";

  return workbook;
}

function addChangesWorkbook(items, auditItems) {
  const workbook = Workbook.create();
  const summary = workbook.worksheets.add("Summary");
  const changes = workbook.worksheets.add("Changes");
  const review = workbook.worksheets.add("Review Queue");
  addAuditSheet(workbook, auditItems);
  const changesLastRow = Math.max(5, items.length + 4);

  setTitle(summary, "Document Change Register", "Risk levels are deterministic review hints, not compliance conclusions.", "H");
  summary.getRange("A4:B4").values = [["Metric", "Value"]];
  styleHeader(summary.getRange("A4:B4"));
  summary.getRange("A5:A9").values = [["Detected changes"], ["High risk"], ["Medium risk"], ["Low risk"], ["Pending review"]];
  summary.getRange("B5:B9").formulas = [[`=COUNTA('Changes'!$A$5:$A$${changesLastRow})`], [`=COUNTIF('Changes'!$E$5:$E$${changesLastRow},"high")`], [`=COUNTIF('Changes'!$E$5:$E$${changesLastRow},"medium")`], [`=COUNTIF('Changes'!$E$5:$E$${changesLastRow},"low")`], [`=COUNTIF('Changes'!$H$5:$H$${changesLastRow},"pending")`]];
  summary.getRange("B5:B9").format.numberFormat = "#,##0";
  summary.getRange("A5:B9").format.borders = { preset: "outside", style: "thin", color: COLORS.lightGray };
  summary.getRange("D4:E4").values = [["Risk", "Count"]];
  styleHeader(summary.getRange("D4:E4"));
  summary.getRange("D5:D7").values = [["High"], ["Medium"], ["Low"]];
  summary.getRange("E5:E7").formulas = [["=B6"], ["=B7"], ["=B8"]];
  const chart = summary.charts.add("bar", summary.getRange("D4:E7"));
  chart.title = "Changes by review risk";
  chart.hasLegend = false;
  chart.xAxis = { axisType: "textAxis" };
  chart.yAxis = { numberFormatCode: "#,##0" };
  chart.setPosition("D9", "H22");
  summary.getRange("A11:B14").merge();
  summary.getRange("A11").values = [["Review high-risk changes first. Confirm source text and business impact before approval or downstream use."]];
  summary.getRange("A11").format = { fill: COLORS.paleAmber, font: { color: "#6B4F00", bold: true }, wrapText: true, verticalAlignment: "top" };
  summary.getRange("A11").format.rowHeight = 70;
  summary.getRange("A4:B14").format.columnWidth = 22;

  const headers = ["Source ID", "Field", "Old Value", "New Value", "Risk Level", "Rationale", "Source Locator", "Review Status"];
  setTitle(changes, "Detected Changes", "Before/after comparison with source locators and explicit review state.", "H");
  changes.getRange("A4:H4").values = [headers];
  styleHeader(changes.getRange("A4:H4"));
  const changeRows = items.map((item) => {
    const [sourceId, field] = splitChangeField(item);
    const sourceLocator = locatorFor(item) || `${sourceId} / ${field}`;
    return [
      sourceId, field, excelSafe(value(item, "old_value")), excelSafe(value(item, "new_value")),
      excelSafe(String(value(item, "risk_level") || "low").toLowerCase()), excelSafe(value(item, "rationale")), excelSafe(sourceLocator), excelSafe(String(value(item, "review_status") || "pending").toLowerCase()),
    ];
  });
  const safeChangeRows = changeRows.length ? changeRows : [["", "", "", "", "low", "", "", "pending"]];
  changes.getRangeByIndexes(4, 0, safeChangeRows.length, headers.length).values = safeChangeRows;
  styleData(changes.getRangeByIndexes(4, 0, safeChangeRows.length, headers.length));
  changes.getRange(`E5:E${safeChangeRows.length + 4}`).dataValidation = { rule: { type: "list", values: ["low", "medium", "high"] } };
  changes.getRange(`H5:H${safeChangeRows.length + 4}`).dataValidation = { rule: { type: "list", values: ["pending", "approved", "rejected"] } };
  changes.getRange(`E5:E${safeChangeRows.length + 4}`).conditionalFormats.add("containsText", { text: "high", format: { fill: COLORS.paleRed, font: { color: "#8A1C1C", bold: true } } });
  changes.getRange(`E5:E${safeChangeRows.length + 4}`).conditionalFormats.add("containsText", { text: "medium", format: { fill: COLORS.paleAmber, font: { color: "#6B4F00" } } });
  changes.getRange(`E5:E${safeChangeRows.length + 4}`).conditionalFormats.add("containsText", { text: "low", format: { fill: COLORS.paleGreen, font: { color: "#155A32" } } });
  [20, 22, 34, 34, 15, 48, 22, 18].forEach((width, index) => changes.getRangeByIndexes(0, index, safeChangeRows.length + 4, 1).format.columnWidth = width);
  changes.freezePanes.freezeRows(4);
  changes.tables.add(`A4:H${safeChangeRows.length + 4}`, true, "DocumentChangesTable").style = "TableStyleMedium2";

  setTitle(review, "Human Review Queue", "Confirm source, impact, and decision before any downstream action.", "J");
  const reviewHeaders = [...headers, "Reviewer Decision", "Reviewer Note"];
  review.getRange("A4:J4").values = [reviewHeaders];
  styleHeader(review.getRange("A4:J4"));
  const reviewRows = safeChangeRows.map((row) => [...row, "pending", ""]);
  review.getRangeByIndexes(4, 0, reviewRows.length, reviewHeaders.length).values = reviewRows;
  styleData(review.getRangeByIndexes(4, 0, reviewRows.length, reviewHeaders.length));
  review.getRange(`I5:I${reviewRows.length + 4}`).dataValidation = { rule: { type: "list", values: ["pending", "approved", "rejected"] } };
  [20, 20, 30, 30, 13, 42, 20, 16, 18, 42].forEach((width, index) => review.getRangeByIndexes(0, index, reviewRows.length + 4, 1).format.columnWidth = width);
  review.freezePanes.freezeRows(4);
  review.tables.add(`A4:J${reviewRows.length + 4}`, true, "ChangeReviewTable").style = "TableStyleMedium2";

  return workbook;
}

function summaryExpectations(kind, items) {
  const lastRow = Math.max(5, items.length + 4);
  if (kind === "evidence") {
    const statuses = items.map((item) => String(value(item, "review_status") || "pending").toLowerCase());
    const confidences = items.map((item) => Number(value(item, "confidence") || 0));
    if (confidences.some((confidence) => !Number.isFinite(confidence))) {
      throw new Error("Evidence confidence values must be finite numbers");
    }
    const averageConfidence = confidences.length
      ? confidences.reduce((total, confidence) => total + confidence, 0) / confidences.length
      : 0;
    return [
      { address: "B5", formula: `=COUNTA('Evidence'!$A$5:$A$${lastRow})`, expectedValue: items.length },
      { address: "B6", formula: `=COUNTIF('Evidence'!$H$5:$H$${lastRow},"pending")`, expectedValue: statuses.filter((status) => status === "pending").length },
      { address: "B7", formula: `=COUNTIF('Evidence'!$H$5:$H$${lastRow},"approved")`, expectedValue: statuses.filter((status) => status === "approved").length },
      { address: "B8", formula: `=COUNTIF('Evidence'!$H$5:$H$${lastRow},"rejected")`, expectedValue: statuses.filter((status) => status === "rejected").length },
      { address: "B9", formula: `=IFERROR(AVERAGE('Evidence'!$G$5:$G$${lastRow}),0)`, expectedValue: averageConfidence },
    ];
  }

  const risks = items.map((item) => String(value(item, "risk_level") || "low").toLowerCase());
  const statuses = items.map((item) => String(value(item, "review_status") || "pending").toLowerCase());
  const high = risks.filter((risk) => risk === "high").length;
  const medium = risks.filter((risk) => risk === "medium").length;
  const low = risks.filter((risk) => risk === "low").length;
  return [
    { address: "B5", formula: `=COUNTA('Changes'!$A$5:$A$${lastRow})`, expectedValue: items.length },
    { address: "B6", formula: `=COUNTIF('Changes'!$E$5:$E$${lastRow},"high")`, expectedValue: high },
    { address: "B7", formula: `=COUNTIF('Changes'!$E$5:$E$${lastRow},"medium")`, expectedValue: medium },
    { address: "B8", formula: `=COUNTIF('Changes'!$E$5:$E$${lastRow},"low")`, expectedValue: low },
    { address: "B9", formula: `=COUNTIF('Changes'!$H$5:$H$${lastRow},"pending")`, expectedValue: statuses.filter((status) => status === "pending").length },
    { address: "E5", formula: "=B6", expectedValue: high },
    { address: "E6", formula: "=B7", expectedValue: medium },
    { address: "E7", formula: "=B8", expectedValue: low },
  ];
}

function verifySummaryFormulas(workbook, expectations) {
  const summary = workbook.worksheets.getItem("Summary");
  return expectations.map(({ address, formula, expectedValue }) => {
    const range = summary.getRange(address);
    const actualFormula = range.formulas?.[0]?.[0];
    const actualValue = range.values?.[0]?.[0];
    if (actualFormula !== formula) {
      throw new Error(`Summary ${address} formula mismatch: expected ${formula}, found ${actualFormula || "<empty>"}`);
    }
    if (typeof actualValue !== "number" || !Number.isFinite(actualValue)) {
      throw new Error(`Summary ${address} must calculate to a finite number; found ${String(actualValue)}`);
    }
    const tolerance = Math.max(1, Math.abs(expectedValue)) * 1e-12;
    if (Math.abs(actualValue - expectedValue) > tolerance) {
      throw new Error(`Summary ${address} value mismatch: expected ${expectedValue}, found ${actualValue}`);
    }
    return { address, formula: actualFormula, value: actualValue };
  });
}

function previewSpecs(kind, itemCount, auditCount) {
  const dataSheet = kind === "evidence" ? "Evidence" : "Changes";
  const dataWidth = kind === "evidence" ? "H" : "H";
  const dataLastRow = Math.min(itemCount, MAX_PREVIEW_DATA_ROWS) + 4;
  const reviewLastRow = Math.min(itemCount, MAX_PREVIEW_DATA_ROWS) + 4;
  const auditLastRow = Math.min(Math.max(auditCount, 1), MAX_PREVIEW_DATA_ROWS) + 4;
  return [
    { sheetName: "Summary", autoCrop: "all" },
    { sheetName: dataSheet, range: `A1:${dataWidth}${dataLastRow}` },
    { sheetName: "Review Queue", range: `A1:J${reviewLastRow}` },
    { sheetName: "Audit", range: `A1:G${auditLastRow}` },
  ];
}

async function verifyAndExport(workbook, kind, items, auditItems, outputPath, verifyDir) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.mkdir(verifyDir, { recursive: true });

  const previews = previewSpecs(kind, items.length, auditItems.length);
  const sheetNames = previews.map(({ sheetName }) => sheetName);
  const summaryFormulaChecks = verifySummaryFormulas(workbook, summaryExpectations(kind, items));

  const inspection = await workbook.inspect({
    kind: "table",
    range: "Summary!A1:H22",
    include: "values,formulas",
    tableMaxRows: 24,
    tableMaxCols: 10,
    maxChars: 8000,
  });

  for (const { sheetName, range, autoCrop } of previews) {
    const blob = await workbook.render({ sheetName, range, autoCrop, scale: 1.4, format: "png" });
    const fileName = `${kind}-${sheetName.toLowerCase().replaceAll(" ", "-")}.png`;
    await fs.writeFile(path.join(verifyDir, fileName), new Uint8Array(await blob.arrayBuffer()));
  }
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
  return {
    inspection: inspection.ndjson,
    summaryFormulaChecks,
    previewRanges: Object.fromEntries(previews.map(({ sheetName, range }) => [sheetName, range || "autoCrop:all"])),
    sheets: sheetNames,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  requireArgs(args, ["kind", "input", "output", "verify-dir"]);
  if (!new Set(["evidence", "changes"]).has(args.kind)) {
    throw new Error("--kind must be evidence or changes");
  }
  const items = await readJson(args.input, args.kind);
  const auditItems = await readAudit(args.audit);
  const workbook = args.kind === "evidence"
    ? addEvidenceWorkbook(items, auditItems)
    : addChangesWorkbook(items, auditItems);
  const result = await verifyAndExport(workbook, args.kind, items, auditItems, args.output, args["verify-dir"]);
  process.stdout.write(`${JSON.stringify({ ok: true, kind: args.kind, output: args.output, itemCount: items.length, ...result }, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
