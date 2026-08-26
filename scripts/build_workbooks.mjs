import fs from "node:fs/promises";
import path from "node:path";

import ExcelJS from "exceljs";

const COLORS = {
  navy: "FF16324F",
  teal: "FF0F766E",
  paleBlue: "FFEAF1F8",
  paleAmber: "FFFFF4D6",
  paleRed: "FFFDE8E7",
  paleGreen: "FFE7F5EC",
  gray: "FF5F6B76",
  lightGray: "FFE2E8F0",
  ink: "FF17212B",
  amberInk: "FF6B4F00",
  redInk: "FF8A1C1C",
  greenInk: "FF155A32",
  white: "FFFFFFFF",
};

const STATUS_VALIDATION = '"pending,approved,rejected"';
const RISK_VALIDATION = '"low,medium,high"';

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (!argument.startsWith("--")) continue;
    const key = argument.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) parsed[key] = true;
    else {
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

function createWorkbook() {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = "regulated-workflow-demo";
  workbook.lastModifiedBy = "regulated-workflow-demo";
  workbook.created = new Date("2026-01-01T00:00:00Z");
  workbook.modified = new Date("2026-01-01T00:00:00Z");
  workbook.calcProperties.fullCalcOnLoad = true;
  workbook.calcProperties.forceFullCalc = true;
  workbook.calcProperties.calcMode = "auto";
  return workbook;
}

function solidFill(color) {
  return { type: "pattern", pattern: "solid", fgColor: { argb: color } };
}

function thinBorder(color = COLORS.lightGray) {
  const side = { style: "thin", color: { argb: color } };
  return { top: side, left: side, bottom: side, right: side };
}

function configureSheet(sheet, freezeRows = 0) {
  sheet.pageSetup = {
    paperSize: 9,
    orientation: "landscape",
    fitToPage: true,
    fitToWidth: 1,
    fitToHeight: 0,
    margins: { left: 0.25, right: 0.25, top: 0.35, bottom: 0.35, header: 0.15, footer: 0.15 },
  };
  sheet.views = freezeRows
    ? [{ state: "frozen", ySplit: freezeRows, topLeftCell: `A${freezeRows + 1}`, activeCell: `A${freezeRows + 1}`, showGridLines: false }]
    : [{ showGridLines: false }];
  if (freezeRows) sheet.pageSetup.printTitlesRow = `1:${freezeRows}`;
}

function setTitle(sheet, title, subtitle, lastColumn) {
  sheet.mergeCells(`A1:${lastColumn}1`);
  const titleCell = sheet.getCell("A1");
  titleCell.value = title;
  titleCell.fill = solidFill(COLORS.navy);
  titleCell.font = { color: { argb: COLORS.white }, bold: true, size: 18 };
  titleCell.alignment = { vertical: "middle" };
  sheet.getRow(1).height = 34;

  sheet.mergeCells(`A2:${lastColumn}2`);
  const subtitleCell = sheet.getCell("A2");
  subtitleCell.value = subtitle;
  subtitleCell.fill = solidFill(COLORS.paleBlue);
  subtitleCell.font = { color: { argb: COLORS.gray }, italic: true, size: 10 };
  subtitleCell.alignment = { vertical: "middle", wrapText: true };
  sheet.getRow(2).height = 30;
}

function styleHeader(sheet, rowNumber, startColumn, endColumn) {
  const row = sheet.getRow(rowNumber);
  row.height = 28;
  for (let column = startColumn; column <= endColumn; column += 1) {
    const cell = row.getCell(column);
    cell.fill = solidFill(COLORS.teal);
    cell.font = { color: { argb: COLORS.white }, bold: true };
    cell.alignment = { vertical: "middle", wrapText: true };
    cell.border = thinBorder(COLORS.teal);
  }
}

function styleData(sheet, startRow, endRow, endColumn) {
  for (let rowNumber = startRow; rowNumber <= endRow; rowNumber += 1) {
    const row = sheet.getRow(rowNumber);
    row.height = 36;
    for (let column = 1; column <= endColumn; column += 1) {
      const cell = row.getCell(column);
      cell.font = { color: { argb: COLORS.ink }, size: 10 };
      cell.alignment = { vertical: "top", wrapText: true };
      cell.border = { bottom: { style: "thin", color: { argb: COLORS.lightGray } } };
    }
  }
}

function setColumnWidths(sheet, widths) {
  widths.forEach((width, index) => {
    sheet.getColumn(index + 1).width = width;
  });
}

function addTable(sheet, name, ref, headers, rows) {
  sheet.addTable({
    name,
    ref,
    headerRow: true,
    totalsRow: false,
    style: {
      theme: "TableStyleMedium2",
      showFirstColumn: false,
      showLastColumn: false,
      showRowStripes: true,
      showColumnStripes: false,
    },
    columns: headers.map((header) => ({ name: header })),
    rows,
  });
}

function addListValidation(sheet, range, formula) {
  sheet.dataValidations.add(range, { type: "list", allowBlank: false, formulae: [formula] });
}

function addTextConditionalFormats(sheet, ref, column, rules) {
  sheet.addConditionalFormatting({
    ref,
    rules: rules.map(({ text, fill, font }, index) => ({
      type: "expression",
      priority: index + 1,
      formulae: [`$${column}5="${text}"`],
      style: {
        fill: solidFill(fill),
        font: { color: { argb: font }, bold: text === "high" },
      },
    })),
  });
}

function setFormula(cell, formula, result) {
  cell.value = { formula, result };
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
  return Number(event.record_count ?? event.count ?? event.evidence_count ?? event.document_count ?? event.change_count ?? 0);
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
  const sheet = workbook.addWorksheet("Audit");
  configureSheet(sheet, 4);
  setTitle(sheet, "Audit Trail", "Run metadata only. Credentials and full environment values are intentionally excluded.", "G");
  const headers = ["Timestamp", "Event", "Command", "Source ID", "Input Hash", "Record Count", "Details"];
  const rows = (auditItems.length ? auditItems : [{ event: "no_audit_events" }]).map((event) => [
    excelSafe(value(event, "timestamp", "time", "created_at")),
    excelSafe(value(event, "event", "event_type", "action")),
    excelSafe(value(event, "command", "workflow", "mode")),
    excelSafe(value(event, "source_id", "source")),
    excelSafe(value(event, "input_hash", "sha256", "hash")),
    auditCount(event),
    auditDetails(event),
  ]);
  addTable(sheet, "AuditEventsTable", "A4", headers, rows);
  styleHeader(sheet, 4, 1, headers.length);
  styleData(sheet, 5, rows.length + 4, headers.length);
  for (let row = 5; row <= rows.length + 4; row += 1) {
    sheet.getCell(row, 1).numFmt = "yyyy-mm-dd hh:mm";
    sheet.getCell(row, 6).numFmt = "#,##0";
  }
  setColumnWidths(sheet, [21, 22, 18, 20, 34, 14, 60]);
  return sheet;
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
      { address: "B5", formula: `COUNTA('Evidence'!$A$5:$A$${lastRow})`, expectedValue: items.length },
      { address: "B6", formula: `COUNTIF('Evidence'!$H$5:$H$${lastRow},"pending")`, expectedValue: statuses.filter((status) => status === "pending").length },
      { address: "B7", formula: `COUNTIF('Evidence'!$H$5:$H$${lastRow},"approved")`, expectedValue: statuses.filter((status) => status === "approved").length },
      { address: "B8", formula: `COUNTIF('Evidence'!$H$5:$H$${lastRow},"rejected")`, expectedValue: statuses.filter((status) => status === "rejected").length },
      { address: "B9", formula: `IFERROR(AVERAGE('Evidence'!$G$5:$G$${lastRow}),0)`, expectedValue: averageConfidence },
    ];
  }
  const risks = items.map((item) => String(value(item, "risk_level") || "low").toLowerCase());
  const statuses = items.map((item) => String(value(item, "review_status") || "pending").toLowerCase());
  const high = risks.filter((risk) => risk === "high").length;
  const medium = risks.filter((risk) => risk === "medium").length;
  const low = risks.filter((risk) => risk === "low").length;
  return [
    { address: "B5", formula: `COUNTA('Changes'!$A$5:$A$${lastRow})`, expectedValue: items.length },
    { address: "B6", formula: `COUNTIF('Changes'!$E$5:$E$${lastRow},"high")`, expectedValue: high },
    { address: "B7", formula: `COUNTIF('Changes'!$E$5:$E$${lastRow},"medium")`, expectedValue: medium },
    { address: "B8", formula: `COUNTIF('Changes'!$E$5:$E$${lastRow},"low")`, expectedValue: low },
    { address: "B9", formula: `COUNTIF('Changes'!$H$5:$H$${lastRow},"pending")`, expectedValue: statuses.filter((status) => status === "pending").length },
    { address: "E5", formula: "B6", expectedValue: high },
    { address: "E6", formula: "B7", expectedValue: medium },
    { address: "E7", formula: "B8", expectedValue: low },
  ];
}

function applySummaryFormulas(summary, expectations) {
  for (const { address, formula, expectedValue } of expectations) setFormula(summary.getCell(address), formula, expectedValue);
}

function verifySummaryFormulas(workbook, expectations) {
  const summary = workbook.getWorksheet("Summary");
  return expectations.map(({ address, formula, expectedValue }) => {
    const cell = summary.getCell(address);
    const cellValue = cell.value;
    const actualFormula = cellValue?.formula;
    // ExcelJS intentionally omits a zero result from cell.value, while cell.result
    // and the serialized <v> still retain it.
    const actualValue = cell.result;
    if (actualFormula !== formula) {
      throw new Error(`Summary ${address} formula mismatch: expected ${formula}, found ${actualFormula || "<empty>"}`);
    }
    if (typeof actualValue !== "number" || !Number.isFinite(actualValue)) {
      throw new Error(`Summary ${address} must have a finite cached result; found ${String(actualValue)}`);
    }
    const tolerance = Math.max(1, Math.abs(expectedValue)) * 1e-12;
    if (Math.abs(actualValue - expectedValue) > tolerance) {
      throw new Error(`Summary ${address} result mismatch: expected ${expectedValue}, found ${actualValue}`);
    }
    return { address, formula: actualFormula, value: actualValue };
  });
}

function addEvidenceWorkbook(items, auditItems) {
  const workbook = createWorkbook();
  const summary = workbook.addWorksheet("Summary");
  const evidence = workbook.addWorksheet("Evidence");
  const review = workbook.addWorksheet("Review Queue");
  addAuditSheet(workbook, auditItems);

  configureSheet(summary);
  setTitle(summary, "Evidence Register", "Draft output for human review — not a compliance determination.", "H");
  summary.getCell("A4").value = "Metric";
  summary.getCell("B4").value = "Value";
  styleHeader(summary, 4, 1, 2);
  ["Evidence items", "Pending review", "Approved", "Rejected", "Average confidence"].forEach((label, index) => {
    summary.getCell(index + 5, 1).value = label;
  });
  const expectations = summaryExpectations("evidence", items);
  applySummaryFormulas(summary, expectations);
  for (let row = 5; row <= 9; row += 1) {
    summary.getCell(row, 1).border = thinBorder();
    summary.getCell(row, 2).border = thinBorder();
    summary.getCell(row, 2).numFmt = row === 9 ? "0.0%" : "#,##0";
  }
  summary.mergeCells("A11:H11");
  const note = summary.getCell("A11");
  note.value = "How to use: verify the quote and locator, choose a review status, and add a reviewer note before treating any row as approved.";
  note.fill = solidFill(COLORS.paleAmber);
  note.font = { color: { argb: COLORS.amberInk }, bold: true };
  note.alignment = { vertical: "middle", wrapText: true };
  summary.getRow(11).height = 36;
  setColumnWidths(summary, [24, 16, 4, 16, 16, 16, 16, 16]);

  const headers = ["Source ID", "Source", "Locator", "Field", "Value", "Quote", "Confidence", "Review Status"];
  const evidenceRows = items.map((item) => [
    excelSafe(value(item, "source_id")), excelSafe(value(item, "source_path", "source", "source_id")), locatorFor(item), excelSafe(value(item, "field")),
    excelSafe(value(item, "value")), excelSafe(value(item, "quote")), Number(value(item, "confidence") || 0), excelSafe(String(value(item, "review_status") || "pending").toLowerCase()),
  ]);
  const safeEvidenceRows = evidenceRows.length ? evidenceRows : [["", "", "", "", "", "", 0, "pending"]];
  configureSheet(evidence, 4);
  setTitle(evidence, "Evidence Items", "Canonical records derived from local sample inputs. Use the review status rather than formatting as the decision field.", "H");
  addTable(evidence, "EvidenceItemsTable", "A4", headers, safeEvidenceRows);
  styleHeader(evidence, 4, 1, headers.length);
  styleData(evidence, 5, safeEvidenceRows.length + 4, headers.length);
  for (let row = 5; row <= safeEvidenceRows.length + 4; row += 1) evidence.getCell(row, 7).numFmt = "0.0%";
  addListValidation(evidence, `H5:H${safeEvidenceRows.length + 4}`, STATUS_VALIDATION);
  addTextConditionalFormats(evidence, `H5:H${safeEvidenceRows.length + 4}`, "H", [
    { text: "pending", fill: COLORS.paleAmber, font: COLORS.amberInk },
    { text: "approved", fill: COLORS.paleGreen, font: COLORS.greenInk },
    { text: "rejected", fill: COLORS.paleRed, font: COLORS.redInk },
  ]);
  setColumnWidths(evidence, [20, 36, 18, 22, 30, 58, 14, 18]);

  const reviewHeaders = [...headers, "Reviewer Decision", "Reviewer Note"];
  const reviewRows = safeEvidenceRows.map((row) => [...row, "pending", ""]);
  configureSheet(review, 4);
  setTitle(review, "Human Review Queue", "Editable decisions are intentionally separate from extracted evidence. Every item begins as pending.", "J");
  addTable(review, "EvidenceReviewTable", "A4", reviewHeaders, reviewRows);
  styleHeader(review, 4, 1, reviewHeaders.length);
  styleData(review, 5, reviewRows.length + 4, reviewHeaders.length);
  for (let row = 5; row <= reviewRows.length + 4; row += 1) review.getCell(row, 7).numFmt = "0.0%";
  addListValidation(review, `I5:I${reviewRows.length + 4}`, STATUS_VALIDATION);
  addTextConditionalFormats(review, `I5:I${reviewRows.length + 4}`, "I", [
    { text: "pending", fill: COLORS.paleAmber, font: COLORS.amberInk },
    { text: "approved", fill: COLORS.paleGreen, font: COLORS.greenInk },
    { text: "rejected", fill: COLORS.paleRed, font: COLORS.redInk },
  ]);
  setColumnWidths(review, [20, 32, 16, 20, 26, 48, 12, 16, 18, 42]);
  return { workbook, expectations };
}

function addChangesWorkbook(items, auditItems) {
  const workbook = createWorkbook();
  const summary = workbook.addWorksheet("Summary");
  const changes = workbook.addWorksheet("Changes");
  const review = workbook.addWorksheet("Review Queue");
  addAuditSheet(workbook, auditItems);

  configureSheet(summary);
  setTitle(summary, "Document Change Register", "Risk levels are deterministic review hints, not compliance conclusions.", "H");
  summary.getCell("A4").value = "Metric";
  summary.getCell("B4").value = "Value";
  styleHeader(summary, 4, 1, 2);
  ["Detected changes", "High risk", "Medium risk", "Low risk", "Pending review"].forEach((label, index) => {
    summary.getCell(index + 5, 1).value = label;
  });
  summary.getCell("D4").value = "Risk";
  summary.getCell("E4").value = "Count";
  styleHeader(summary, 4, 4, 5);
  ["High", "Medium", "Low"].forEach((label, index) => {
    const cell = summary.getCell(index + 5, 4);
    cell.value = label;
    cell.fill = solidFill([COLORS.paleRed, COLORS.paleAmber, COLORS.paleGreen][index]);
    cell.font = { bold: true, color: { argb: [COLORS.redInk, COLORS.amberInk, COLORS.greenInk][index] } };
  });
  const expectations = summaryExpectations("changes", items);
  applySummaryFormulas(summary, expectations);
  for (let row = 5; row <= 9; row += 1) {
    summary.getCell(row, 1).border = thinBorder();
    summary.getCell(row, 2).border = thinBorder();
    summary.getCell(row, 2).numFmt = "#,##0";
  }
  for (let row = 5; row <= 7; row += 1) {
    summary.getCell(row, 4).border = thinBorder();
    summary.getCell(row, 5).border = thinBorder();
    summary.getCell(row, 5).numFmt = "#,##0";
  }
  summary.mergeCells("A11:B14");
  const note = summary.getCell("A11");
  note.value = "Review high-risk changes first. Confirm source text and business impact before approval or downstream use.";
  note.fill = solidFill(COLORS.paleAmber);
  note.font = { color: { argb: COLORS.amberInk }, bold: true };
  note.alignment = { vertical: "top", wrapText: true };
  summary.getRow(11).height = 70;
  setColumnWidths(summary, [24, 16, 4, 16, 14, 14, 14, 14]);

  const headers = ["Source ID", "Field", "Old Value", "New Value", "Risk Level", "Rationale", "Source Locator", "Review Status"];
  const changeRows = items.map((item) => {
    const [sourceId, field] = splitChangeField(item);
    const sourceLocator = locatorFor(item) || `${sourceId} / ${field}`;
    return [
      sourceId, field, excelSafe(value(item, "old_value")), excelSafe(value(item, "new_value")),
      excelSafe(String(value(item, "risk_level") || "low").toLowerCase()), excelSafe(value(item, "rationale")), excelSafe(sourceLocator), excelSafe(String(value(item, "review_status") || "pending").toLowerCase()),
    ];
  });
  const safeChangeRows = changeRows.length ? changeRows : [["", "", "", "", "low", "", "", "pending"]];
  configureSheet(changes, 4);
  setTitle(changes, "Detected Changes", "Before/after comparison with source locators and explicit review state.", "H");
  addTable(changes, "DocumentChangesTable", "A4", headers, safeChangeRows);
  styleHeader(changes, 4, 1, headers.length);
  styleData(changes, 5, safeChangeRows.length + 4, headers.length);
  addListValidation(changes, `E5:E${safeChangeRows.length + 4}`, RISK_VALIDATION);
  addListValidation(changes, `H5:H${safeChangeRows.length + 4}`, STATUS_VALIDATION);
  addTextConditionalFormats(changes, `E5:E${safeChangeRows.length + 4}`, "E", [
    { text: "high", fill: COLORS.paleRed, font: COLORS.redInk },
    { text: "medium", fill: COLORS.paleAmber, font: COLORS.amberInk },
    { text: "low", fill: COLORS.paleGreen, font: COLORS.greenInk },
  ]);
  addTextConditionalFormats(changes, `H5:H${safeChangeRows.length + 4}`, "H", [
    { text: "pending", fill: COLORS.paleAmber, font: COLORS.amberInk },
    { text: "approved", fill: COLORS.paleGreen, font: COLORS.greenInk },
    { text: "rejected", fill: COLORS.paleRed, font: COLORS.redInk },
  ]);
  setColumnWidths(changes, [20, 22, 34, 34, 15, 48, 22, 18]);

  const reviewHeaders = [...headers, "Reviewer Decision", "Reviewer Note"];
  const reviewRows = safeChangeRows.map((row) => [...row, "pending", ""]);
  configureSheet(review, 4);
  setTitle(review, "Human Review Queue", "Confirm source, impact, and decision before any downstream action.", "J");
  addTable(review, "ChangeReviewTable", "A4", reviewHeaders, reviewRows);
  styleHeader(review, 4, 1, reviewHeaders.length);
  styleData(review, 5, reviewRows.length + 4, reviewHeaders.length);
  addListValidation(review, `I5:I${reviewRows.length + 4}`, STATUS_VALIDATION);
  addTextConditionalFormats(review, `I5:I${reviewRows.length + 4}`, "I", [
    { text: "pending", fill: COLORS.paleAmber, font: COLORS.amberInk },
    { text: "approved", fill: COLORS.paleGreen, font: COLORS.greenInk },
    { text: "rejected", fill: COLORS.paleRed, font: COLORS.redInk },
  ]);
  setColumnWidths(review, [20, 20, 30, 30, 13, 42, 20, 16, 18, 42]);
  return { workbook, expectations };
}

function inspectionRecords(workbook, formulaChecks) {
  const records = workbook.worksheets.map((sheet) => ({
    type: "worksheet",
    sheet: sheet.name,
    rowCount: sheet.rowCount,
    columnCount: sheet.columnCount,
    tables: Object.values(sheet.tables).map((table) => ({ name: table.name, ref: table.table.tableRef })),
  }));
  records.push({ type: "summary_formula_checks", checks: formulaChecks });
  return records;
}

async function verifyAndExport(workbook, expectations, kind, outputPath, verifyDir) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.mkdir(verifyDir, { recursive: true });
  const summaryFormulaChecks = verifySummaryFormulas(workbook, expectations);
  await workbook.xlsx.writeFile(outputPath, { useStyles: true, useSharedStrings: true });
  const inspection = `${inspectionRecords(workbook, summaryFormulaChecks).map((record) => JSON.stringify(record)).join("\n")}\n`;
  const inspectionPath = `${outputPath}.inspect.ndjson`;
  await fs.writeFile(inspectionPath, inspection, "utf8");
  await fs.writeFile(
    path.join(verifyDir, `${kind}-workbook-inspection.json`),
    `${JSON.stringify({ kind, output: outputPath, sheets: workbook.worksheets.map((sheet) => sheet.name), summaryFormulaChecks }, null, 2)}\n`,
    "utf8",
  );
  return { inspectionPath, summaryFormulaChecks, sheets: workbook.worksheets.map((sheet) => sheet.name) };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  requireArgs(args, ["kind", "input", "output", "verify-dir"]);
  if (!new Set(["evidence", "changes"]).has(args.kind)) throw new Error("--kind must be evidence or changes");
  const items = await readJson(args.input, args.kind);
  const auditItems = await readAudit(args.audit);
  const { workbook, expectations } = args.kind === "evidence"
    ? addEvidenceWorkbook(items, auditItems)
    : addChangesWorkbook(items, auditItems);
  const result = await verifyAndExport(workbook, expectations, args.kind, args.output, args["verify-dir"]);
  process.stdout.write(`${JSON.stringify({ ok: true, kind: args.kind, output: args.output, itemCount: items.length, ...result }, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
