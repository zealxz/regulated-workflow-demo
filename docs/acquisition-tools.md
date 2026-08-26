# Review-Only Acquisition Utilities

These optional developer utilities are not part of the document-workflow pilot. They generate drafts for human review and never submit proposals, send messages, scrape authenticated pages, or modify external accounts.

## Offline Lead Assistant

Use `leads` with a manually collected public-lead CSV:

```bash
PYTHONPATH=src python3 -m regulated_workflow leads samples/leads.csv --output-dir outputs/leads
```

For repeatable age calculation, supply a timezone-aware reference time:

```bash
PYTHONPATH=src python3 -m regulated_workflow leads leads.csv \
  --output-dir outputs/leads \
  --as-of 2026-08-26T12:00:00+08:00
```

To prevent a previously closed, unsafe, or permanently excluded stable lead ID from producing another draft, supply a separate suppression CSV:

```bash
PYTHONPATH=src python3 -m regulated_workflow leads leads.csv \
  --output-dir outputs/leads \
  --suppressions lead-suppressions.csv
```

The suppression CSV requires unique, non-empty `lead_id,reason` rows. Additional columns are ignored and IDs match case-insensitively. Keep reasons short, operational, and non-personal—for example `request closed` or `outside safe scope`. A suppressed row stays visible with its original score in `ranked_leads.csv`, but is forced to `qualified=false` and `draft_type=none`; the stable ID and reason are recorded in the minimized audit trail and never copied into a message draft. CSV output retains spreadsheet-formula-injection protection.

Input columns:

| Column | Rule |
| --- | --- |
| `lead_id`, `channel`, `title`, `description` | Required for every row. IDs must be unique. |
| `age_hours` or `published_at` | At least one is required. `age_hours` takes precedence; timestamps must include a timezone. |
| `proposals`, `payment_verified` | Required for Upwork; optional for domestic/public channels. Proposal ranges are interpreted conservatively. |
| `accepting_outreach` | `yes`/`open` means explicitly accepting contact; `no`/`closed` can never qualify. Blank or `unknown` remains unverified. |
| `url`, `client_name`, `notes` | Optional review context. URLs must be public HTTP(S) URLs without embedded credentials. |

Supported channels are `upwork`, `v2ex`, `proginn`/`程序员客栈`, and `public`/`公开需求`. Upwork drafts require a post no older than two hours, fewer than 20 proposals, verified payment, and at least two demo-match themes. Domestic/public drafts require the demo-match gate. Every generated message remains unsubmitted.

Generated files are `ranked_leads.csv`, `upwork_proposals.md`, `domestic_messages.md`, `summary.md`, and `audit.jsonl`. Review the original post and correct every assumption before manually sending anything.

## Bounded V2EX Discovery

This explicit command makes exactly one unauthenticated request to V2EX's fixed public outsourcing-node endpoint, examines at most 20 topics, and writes a minimized CSV accepted by `leads`:

```bash
PYTHONPATH=src python3 -m regulated_workflow v2ex-discover outputs/v2ex-public.csv
PYTHONPATH=src python3 -m regulated_workflow leads outputs/v2ex-public.csv \
  --output-dir outputs/v2ex-ranked
```

A row is retained only when deterministic rules find relevant workflow themes and explicit buyer or paid-test intent, while rejecting seller offers and medical, psychological, legal-advice, investment, or financial-trading topics. External links, contact channels, and opaque encoded-looking tokens are removed without decoding.

The command refuses redirects, credentials, cookies, pagination, retries, reply fetching, and sending. Because replies are deliberately not fetched, `unknown` availability requires a manual check of the original topic before any outreach.

First-party basis: V2EX's official [legacy topic endpoint page](https://www.v2ex.com/t/2241) documents unauthenticated `GET`; a first-party [node JSON explanation](https://www.v2ex.com/t/1187622) confirms the `node_name` form and 20-topic limit; [API 2.0 documentation](https://www.v2ex.com/help/api) describes token access, which this project does not use.

## Prohibited Use

Do not use these utilities for authenticated scraping, auto-refreshing, bulk outreach, duplicate posting, contact-detail harvesting, decoding hidden contact data, engagement manipulation, or free customer-specific deliverables.
