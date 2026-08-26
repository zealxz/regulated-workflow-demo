# Regulated Workflow Demo

[![tests](https://github.com/zealxz/regulated-workflow-demo/actions/workflows/tests.yml/badge.svg)](https://github.com/zealxz/regulated-workflow-demo/actions/workflows/tests.yml)

Local-first Python workflows for extracting auditable evidence and reviewing controlled-document changes. Every result is a draft for human review; the project does not make compliance, legal, medical, financial, or approval decisions.

The included fixtures are synthetic and describe no real organization.

![Auditable evidence workflow preview](artifacts/portfolio/evidence-cover.png)

[Watch the 30-second evidence demo](artifacts/portfolio/evidence-demo.mp4) · [Watch the 30-second change-review demo](artifacts/portfolio/changes-demo.mp4)

![Controlled change review preview](artifacts/portfolio/changes-cover.png)

## Fixed-Scope Pilot

I offer a seven-day pilot that turns one repetitive document or data process into a client-owned, reviewable Python workflow. The first two pilots are `$149` / `¥999`: one data source, up to 20 representative documents or 500 rows, one extraction/validation/comparison flow, one structured output, one human approval point, one bounded correction round, deployment notes, and seven days of defect support.

Only public, properly redacted, or synthetic samples are used for the pilot. It excludes production hosting, automatic external sending, access-control bypass, autonomous high-impact decisions, and legal, medical, financial, or compliance conclusions. Contact through my [Upwork profile](https://www.upwork.com/freelancers/~017eff134da27928bc), or [open a public scope inquiry](https://github.com/zealxz/regulated-workflow-demo/issues/new?template=pilot-inquiry.yml) without confidential data.

## What It Demonstrates

- `extract`: local TXT, Markdown, CSV, JSON, and optional PDF → evidence register and review queue.
- `diff`: two local snapshots → explainable old/new changes and review priority.
- `leads`: one manually collected public-lead CSV → transparent ranking and unsubmitted message drafts.
- `v2ex-discover`: one explicit, bounded public V2EX read → minimized, contact-redacted lead CSV for the offline ranker.
- Canonical JSON plus CSV, Markdown, JSONL, and formatted Excel outputs.
- Stable source IDs, hashes, explicit offline audit events, and spreadsheet-formula-injection protection.
- An optional OpenAI-compatible summary adapter that is disabled by default and receives aggregate counts only.

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

Excel export uses Node.js 20+ and `@oai/artifact-tool` 2.8.6+. Inside Codex Desktop, use the bundled workspace dependency runtime. Outside that environment, use `--skip-workbooks` unless a compatible package is available.

```bash
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
regulated-workflow leads INPUT.csv --output-dir DIR [--as-of ISO-8601]
regulated-workflow v2ex-discover OUTPUT.csv [--max-topics 1..20]
```

Supported inputs are `.txt`, `.md`, `.csv`, `.json`, and `.pdf`. PDF support is optional:

```bash
python3 -m pip install '.[pdf]'
```

Unsupported files inside a directory are ignored. An explicitly supplied unsupported file, malformed supported file, missing path, or unsafe output collision fails visibly with exit code `2`.

## Offline Lead Assistant

Use the `leads` command with a CSV you collected manually from public posts. The command does not open a browser, fetch a URL, use credentials, submit proposals, or send messages.

```bash
PYTHONPATH=src python3 -m regulated_workflow leads samples/leads.csv --output-dir outputs/leads
```

For a repeatable age calculation from `published_at`, supply a timezone-aware reference time:

```bash
PYTHONPATH=src python3 -m regulated_workflow leads leads.csv \
  --output-dir outputs/leads \
  --as-of 2026-08-26T12:00:00+08:00
```

Input columns:

| Column | Rule |
| --- | --- |
| `lead_id`, `channel`, `title`, `description` | Required for every row. IDs must be unique. |
| `age_hours` or `published_at` | At least one is required. `age_hours` takes precedence; timestamps must include a timezone. |
| `proposals`, `payment_verified` | Required for Upwork; optional and treated as not applicable for domestic channels. Common Upwork ranges such as `Less than 5`, `10 to 15`, and `20 to 50` are accepted conservatively. |
| `accepting_outreach` | Optional manual availability check: `yes`/`open` means explicitly accepting contact; `no`/`closed` means the post is explicitly closed and can never qualify. Leave blank when unknown; the output preserves `unknown` and does not claim the lead is open. |
| `url`, `client_name`, `notes` | Optional review context. URLs, when present, must be public HTTP(S) URLs without embedded credentials. |

Supported channels are `upwork`, `v2ex`, `proginn`/`程序员客栈`, and `public`/`公开需求`. Upwork drafts require all four gates: posted within two hours, fewer than 20 proposals, payment verified, and at least two demo-match themes. Domestic drafts require the demo-match gate; recency still contributes to ranking. Match themes cover document processing, auditability, workflow/API automation, and AI/retrieval.

Generated files:

| File | Purpose |
| --- | --- |
| `ranked_leads.csv` | Qualified rows first, then normalized score, recency, and stable lead ID; includes every score component, applicable maximum, and failed gate. Domestic rows are not penalized for inapplicable proposal/payment fields. |
| `upwork_proposals.md` | Review-only English drafts; every proposal body is checked to contain 120–160 words. |
| `domestic_messages.md` | Review-only Chinese V2EX/程序员客栈/public-post drafts. |
| `summary.md`, `audit.jsonl` | Rule summary and an offline/no-external-action audit record. |

Review the original post and edit assumptions before manually sending a draft. Do not use this helper for authenticated scraping, auto-refreshing, bulk outreach, duplicate posting, or free customer-specific deliverables.

## Bounded V2EX Discovery

This optional command makes exactly one no-authenticated request to V2EX's fixed public outsourcing-node endpoint, examines at most 20 topics, and writes a CSV accepted by the offline `leads` command:

```bash
PYTHONPATH=src python3 -m regulated_workflow v2ex-discover outputs/v2ex-public.csv
PYTHONPATH=src python3 -m regulated_workflow leads outputs/v2ex-public.csv \
  --output-dir outputs/v2ex-ranked
```

A row is retained only when deterministic rules find relevant workflow themes and explicit buyer or paid-test intent, while rejecting seller `接单`/`承接` offers and medical, psychological, legal-advice, investment, or financial-trading topics. External links, contact channels, and opaque encoded-looking tokens are removed without decoding. The command refuses redirects, credentials, cookies, pagination, retries, reply fetching, and sending. Because replies are deliberately not fetched, `unknown` availability requires a manual check of the original topic before any outreach.

First-party basis: V2EX's official [legacy topic endpoint page](https://www.v2ex.com/t/2241) documents unauthenticated `GET`; a first-party [node JSON explanation](https://www.v2ex.com/t/1187622) confirms the `node_name` form and 20-topic limitation; [API 2.0 documentation](https://www.v2ex.com/help/api) describes token access, which this project intentionally does not use.

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
python3 scripts/run_demo.py --skip-workbooks
python3 scripts/verify_outputs.py outputs/extract outputs/diff --skip-workbooks
```

The bounded seven-day pilot scope is documented in [`docs/service-scope.md`](docs/service-scope.md).

Ready-to-review 4:3 portfolio images and two silent 30-second H.264 demos are under [`artifacts/portfolio/`](artifacts/portfolio/). Their source hashes and output hashes are recorded in `artifacts/portfolio/manifest.json`; all visuals are derived from the verified synthetic demo run.

## 中文简介

这是一个完全使用合成样例的本地文档工作流演示：`extract` 生成带来源定位和人工复核状态的证据台账，`diff` 生成旧值、新值与可解释的复核优先级。默认不联网、不自动发送、不作合规结论，JSON 为事实源，Excel 为可编辑展示层。

## License

MIT
