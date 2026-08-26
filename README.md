# Auditable Document Workflow Automation

[![tests](https://github.com/zealxz/regulated-workflow-demo/actions/workflows/tests.yml/badge.svg)](https://github.com/zealxz/regulated-workflow-demo/actions/workflows/tests.yml)

Turn text-layer PDFs, CSV tables, and controlled-document versions into source-linked evidence registers and review queues—local-first, with human approval. Excel workbooks are review outputs, not input files; scanned PDFs and OCR require a separately agreed dependency and acceptance sample.

## Seven-Day Fixed-Scope Pilot

The first two pilots are `$149` / `¥999`:

- **7 calendar days**
- **up to 20 representative documents or 500 rows**
- **one extraction, validation, or comparison workflow**
- **one structured output and one human approval point**

Choose one buyer-ready result:

- **Evidence extraction:** text-layer PDF, text, JSON, or CSV input → `evidence.xlsx` + `review_queue.csv`.
- **Controlled change review:** old/new document snapshots → `changes.xlsx` + approval-ready `summary.md`.

The pilot also includes one bounded correction round, deployment notes, and seven days of defect support. The workflow is client-owned and runs in the client's environment.

[Inspect verified sample outputs](#verified-sample-outputs) · [Watch the 30-second evidence demo](artifacts/portfolio/evidence-demo.mp4) · [Watch the 30-second change-review demo](artifacts/portfolio/changes-demo.mp4)

**Contact:** [purchase or scope the pilot through Upwork](https://www.upwork.com/services/product/development-it-a-7-day-auditable-document-workflow-automation-sprint-2092293814461481436) · [public scope inquiry](https://github.com/zealxz/regulated-workflow-demo/issues/new?template=pilot-inquiry.yml) (do not include confidential data)

If you reached this demo through a marketplace, keep scoping, contracting, and payment on that same marketplace. Otherwise use the Upwork Catalog or the public fit check above.

**Safety boundary:** only public, properly redacted, or synthetic samples are used. The pilot excludes production hosting, automatic external sending, access-control bypass, autonomous high-impact decisions, and legal, medical, financial, compliance, or approval conclusions.

## 中文服务简介

把文本型 PDF、CSV 表格和版本文档转成带来源定位的证据台账、差异清单与人工复核队列；Excel 是复核输出，不是输入格式，扫描件与 OCR 依赖需另行约定验收样本。首两单为 7 日固定范围试点，价格 `¥999`：最多 20 份文档或 500 行、一个流程、一个结构化输出、一个人工审批点、一次限定修正和 7 天缺陷支持。演示全部使用合成数据，不冒充客户案例，不作合规结论。

[查看可下载样例](#verified-sample-outputs) · [通过 Upwork 购买或沟通](https://www.upwork.com/services/product/development-it-a-7-day-auditable-document-workflow-automation-sprint-2092293814461481436) · [公开咨询](https://github.com/zealxz/regulated-workflow-demo/issues/new?template=pilot-inquiry.yml)

如果你从程序员客栈、YesPMP、PeoplePerHour 等平台看到此演示，请继续在原平台沟通、签约和付款；不要跨平台交易。

![Auditable evidence workflow preview](artifacts/portfolio/evidence-cover.png)

[Watch the 30-second evidence demo](artifacts/portfolio/evidence-demo.mp4) · [Watch the 30-second change-review demo](artifacts/portfolio/changes-demo.mp4)

![Controlled change review preview](artifacts/portfolio/changes-cover.png)

## What This Demo Proves

- `extract`: local TXT, Markdown, CSV, JSON, and optional text-layer PDF → source-linked evidence register and review queue.
- The optional PDF path has a real, single-page synthetic extraction fixture and regression test in CI.
- `diff`: two local snapshots → explainable old/new changes and review priority.
- Canonical JSON plus CSV, Markdown, JSONL, and formatted Excel outputs.
- Stable source IDs, hashes, explicit offline audit events, and spreadsheet-formula-injection protection.
- An optional OpenAI-compatible summary adapter that is disabled by default and receives aggregate counts only.

## Verified Sample Outputs

These downloadable artifacts were generated from the repository's synthetic fixtures. Every decision field starts as `pending`, and the committed workbooks are checked against the canonical records in CI.

| Workflow | Inspect the deliverables |
| --- | --- |
| Evidence extraction | [`evidence.xlsx`](outputs/extract/evidence.xlsx) · [`review_queue.csv`](outputs/extract/review_queue.csv) · [`audit.jsonl`](outputs/extract/audit.jsonl) · [`summary.md`](outputs/extract/summary.md) |
| Controlled change review | [`changes.xlsx`](outputs/diff/changes.xlsx) · [`review_queue.csv`](outputs/diff/review_queue.csv) · [`audit.jsonl`](outputs/diff/audit.jsonl) · [`summary.md`](outputs/diff/summary.md) |
| Text-layer PDF proof | [`synthetic-policy.pdf`](samples/pdf/synthetic-policy.pdf) → [`evidence.xlsx`](outputs/pdf-extract/evidence.xlsx) · [`evidence.json`](outputs/pdf-extract/evidence.json) · [`review_queue.csv`](outputs/pdf-extract/review_queue.csv) · [`audit.jsonl`](outputs/pdf-extract/audit.jsonl) · [`summary.md`](outputs/pdf-extract/summary.md) |

The verifier confirms 26 evidence items and 13 changes, workbook relationships and sheets, table ranges, data validation, formulas and cached values, review defaults, and final rows.

The committed PDF proof extracts eight page-1 records, including `Policy ID = SYN-PDF-001`, `Owner = Quality Operations`, and `Review Cycle Months = 6`; all remain `pending` for human review. OCR is intentionally outside this demo.

[![Rendered text-layer PDF evidence workbook](artifacts/proof/pdf-evidence-proof.png)](outputs/pdf-extract/evidence.xlsx)

The image above is a direct LibreOffice render of the committed workbook, not a design mockup. Click it to download the review-ready Excel file.

## Quick Start: Offline Canonical Outputs

Python 3.9 or later is sufficient for TXT, Markdown, CSV, and JSON.

```bash
PYTHONPATH=src python3 -m regulated_workflow extract samples/new --output-dir outputs/extract
PYTHONPATH=src python3 -m regulated_workflow diff samples/old samples/new --output-dir outputs/diff
python3 scripts/verify_outputs.py outputs/extract outputs/diff --skip-workbooks
```

Or run both workflows:

```bash
python3 scripts/run_demo.py --skip-workbooks
```

## Full Demo With Excel Workbooks

Excel export uses Node.js 20+ and the publicly installable, lockfile-pinned ExcelJS dependency. Install it once in a normal clone; `npm ci` reproduces the exact reviewed dependency tree.

```bash
npm ci
npm run test:workbooks
python3 scripts/run_demo.py
python3 scripts/verify_outputs.py outputs/extract outputs/diff
```

Generated files:

| Workflow | Canonical | Review and presentation |
| --- | --- | --- |
| Extract | `evidence.json`, `audit.jsonl` | `evidence.xlsx`, `review_queue.csv`, `summary.md` |
| Diff | `changes.json`, `audit.jsonl` | `changes.xlsx`, `review_queue.csv`, `summary.md` |

Workbook summaries are formula-backed. Evidence and review sheets have filters, frozen headers, explicit status fields, data validation, and visible human-approval warnings.

## Direct CLI

```text
regulated-workflow extract INPUT --output-dir DIR [--llm-summary]
regulated-workflow diff OLD NEW --output-dir DIR [--llm-summary]
```

Supported inputs are `.txt`, `.md`, `.csv`, `.json`, and text-layer `.pdf`. PDF support is optional; scanned PDFs and OCR are not included:

```bash
python3 -m pip install '.[pdf]'
```

Unsupported files inside a directory are ignored. An explicitly supplied unsupported file, malformed supported file, missing path, or unsafe output collision fails visibly with exit code `2`.

## Optional Counts-Only LLM Draft

The network path is never enabled implicitly. `--llm-summary` requires all three environment variables:

```bash
export REGULATED_WORKFLOW_OPENAI_BASE_URL='https://provider.example/v1'
export REGULATED_WORKFLOW_OPENAI_API_KEY='set-in-your-secret-manager'
export REGULATED_WORKFLOW_OPENAI_MODEL='your-model'
```

Only aggregate document/change counts are sent. Source text, field names, values, file paths, and quotes are excluded. The remote draft remains explicitly unreviewed.

## Safety Boundaries

- Select input folders explicitly; the CLI does not scan adjacent projects.
- Use public, synthetic, or properly authorized and minimized input data.
- Treat confidence and risk as review aids, not conclusions.
- Do not connect the demo to external sending or data mutation without a separately reviewed scope.
- Keep API keys out of files, logs, screenshots, proposals, and command-line arguments.
- JSON is canonical; spreadsheets are editable presentation artifacts.

## Verification

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
npm ci
npm run test:workbooks
python3 scripts/run_demo.py
python3 scripts/verify_outputs.py outputs/extract outputs/diff
```

The bounded seven-day pilot scope is documented in [`docs/service-scope.md`](docs/service-scope.md).

Ready-to-review 4:3 portfolio images and two silent 30-second H.264 demos are under [`artifacts/portfolio/`](artifacts/portfolio/). Their source hashes and output hashes are recorded in `artifacts/portfolio/manifest.json`; all visuals are derived from the verified synthetic demo run.

## License

MIT
