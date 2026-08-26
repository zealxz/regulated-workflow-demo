import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import ExcelJS from "exceljs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const STATUS_VALIDATION = '"pending,approved,rejected"';
const RISK_VALIDATION = '"low,medium,high"';

async function buildWorkbook(kind, input, audit, output, verifyDir) {
  const result = spawnSync(
    process.execPath,
    [
      "scripts/build_workbooks.mjs",
      "--kind", kind,
      "--input", input,
      "--audit", audit,
      "--output", output,
      "--verify-dir", verifyDir,
    ],
    { cwd: ROOT, encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return JSON.parse(result.stdout);
}

async function loadWorkbook(filePath) {
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.readFile(filePath);
  return workbook;
}

function assertFormula(sheet, address, formula, result) {
  const cell = sheet.getCell(address);
  const cellValue = cell.value;
  assert.equal(cellValue.formula, formula);
  assert.equal(cell.result, result);
}

function assertValidation(sheet, column, firstRow, lastRow, formula) {
  for (let row = firstRow; row <= lastRow; row += 1) {
    assert.equal(sheet.getCell(`${column}${row}`).dataValidation.formulae[0], formula);
  }
}

test("evidence exporter preserves tables, validations, and cached formulas", async (context) => {
  const temporaryRoot = await fs.mkdtemp(path.join(os.tmpdir(), "regulated-evidence-"));
  context.after(() => fs.rm(temporaryRoot, { recursive: true, force: true }));
  const output = path.join(temporaryRoot, "evidence.xlsx");
  const result = await buildWorkbook(
    "evidence",
    path.join(ROOT, "outputs/extract/evidence.json"),
    path.join(ROOT, "outputs/extract/audit.jsonl"),
    output,
    path.join(temporaryRoot, "verification"),
  );
  assert.deepEqual(result.sheets, ["Summary", "Evidence", "Review Queue", "Audit"]);

  const items = JSON.parse(await fs.readFile(path.join(ROOT, "outputs/extract/evidence.json"), "utf8"));
  const workbook = await loadWorkbook(output);
  const lastRow = items.length + 4;
  const summary = workbook.getWorksheet("Summary");
  assertFormula(summary, "B5", `COUNTA('Evidence'!$A$5:$A$${lastRow})`, items.length);
  assertFormula(summary, "B6", `COUNTIF('Evidence'!$H$5:$H$${lastRow},"pending")`, items.length);
  assertFormula(summary, "B7", `COUNTIF('Evidence'!$H$5:$H$${lastRow},"approved")`, 0);
  assert.equal(workbook.getWorksheet("Evidence").getTable("EvidenceItemsTable").table.tableRef, `A4:H${lastRow}`);
  assert.equal(workbook.getWorksheet("Review Queue").getTable("EvidenceReviewTable").table.tableRef, `A4:J${lastRow}`);
  assertValidation(workbook.getWorksheet("Evidence"), "H", 5, lastRow, STATUS_VALIDATION);
});

test("changes exporter preserves tables, validations, and cached formulas", async (context) => {
  const temporaryRoot = await fs.mkdtemp(path.join(os.tmpdir(), "regulated-changes-"));
  context.after(() => fs.rm(temporaryRoot, { recursive: true, force: true }));
  const output = path.join(temporaryRoot, "changes.xlsx");
  const result = await buildWorkbook(
    "changes",
    path.join(ROOT, "outputs/diff/changes.json"),
    path.join(ROOT, "outputs/diff/audit.jsonl"),
    output,
    path.join(temporaryRoot, "verification"),
  );
  assert.deepEqual(result.sheets, ["Summary", "Changes", "Review Queue", "Audit"]);

  const items = JSON.parse(await fs.readFile(path.join(ROOT, "outputs/diff/changes.json"), "utf8"));
  const high = items.filter((item) => String(item.risk_level || "low").toLowerCase() === "high").length;
  const workbook = await loadWorkbook(output);
  const lastRow = items.length + 4;
  const summary = workbook.getWorksheet("Summary");
  assertFormula(summary, "B5", `COUNTA('Changes'!$A$5:$A$${lastRow})`, items.length);
  assertFormula(summary, "B6", `COUNTIF('Changes'!$E$5:$E$${lastRow},"high")`, high);
  assertFormula(summary, "E5", "B6", high);
  assertFormula(summary, "B8", `COUNTIF('Changes'!$E$5:$E$${lastRow},"low")`, 0);
  assert.equal(workbook.getWorksheet("Changes").getTable("DocumentChangesTable").table.tableRef, `A4:H${lastRow}`);
  assert.equal(workbook.getWorksheet("Review Queue").getTable("ChangeReviewTable").table.tableRef, `A4:J${lastRow}`);
  assertValidation(workbook.getWorksheet("Changes"), "E", 5, lastRow, RISK_VALIDATION);
  assertValidation(workbook.getWorksheet("Changes"), "H", 5, lastRow, STATUS_VALIDATION);
});

test("committed text-layer PDF workbook matches its canonical proof", async (context) => {
  const proofRoot = path.join(ROOT, "outputs/pdf-extract");
  const temporaryRoot = await fs.mkdtemp(path.join(os.tmpdir(), "regulated-pdf-proof-"));
  context.after(() => fs.rm(temporaryRoot, { recursive: true, force: true }));
  const regenerated = path.join(temporaryRoot, "evidence.xlsx");
  await buildWorkbook(
    "evidence",
    path.join(proofRoot, "evidence.json"),
    path.join(proofRoot, "audit.jsonl"),
    regenerated,
    path.join(temporaryRoot, "verification"),
  );

  const items = JSON.parse(await fs.readFile(path.join(proofRoot, "evidence.json"), "utf8"));
  const expectedRows = items.map((item) => [
    item.source_id,
    item.source_id,
    `page ${item.page}`,
    item.field,
    item.value,
    item.quote,
    item.confidence,
    item.review_status,
  ]);
  for (const candidate of [regenerated, path.join(proofRoot, "evidence.xlsx")]) {
    const workbook = await loadWorkbook(candidate);
    const evidence = workbook.getWorksheet("Evidence");
    const actualRows = [];
    for (let row = 5; row < 5 + items.length; row += 1) {
      actualRows.push([
        evidence.getCell(`A${row}`).value,
        evidence.getCell(`B${row}`).value,
        evidence.getCell(`C${row}`).value,
        evidence.getCell(`D${row}`).value,
        evidence.getCell(`E${row}`).value,
        evidence.getCell(`F${row}`).value,
        evidence.getCell(`G${row}`).value,
        evidence.getCell(`H${row}`).value,
      ]);
    }
    assert.deepEqual(actualRows, expectedRows);
    assertFormula(
      workbook.getWorksheet("Summary"),
      "B5",
      "COUNTA('Evidence'!$A$5:$A$12)",
      items.length,
    );
  }
});
