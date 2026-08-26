import csv
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from regulated_workflow.errors import InputError
from regulated_workflow.cli import main
from regulated_workflow.leads import count_english_words, run_lead_assistant


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT_ROOT / "samples" / "leads.csv"


class LeadAssistantTests(unittest.TestCase):
    def test_ranks_manual_csv_and_generates_review_only_drafts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "leads"

            paths = run_lead_assistant(SAMPLE, output_dir)

            self.assertEqual(5, len(paths))
            self.assertEqual(
                {
                    "audit.jsonl",
                    "domestic_messages.md",
                    "ranked_leads.csv",
                    "summary.md",
                    "upwork_proposals.md",
                },
                {path.name for path in paths},
            )
            with (output_dir / "ranked_leads.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(5, len(rows))
            by_id = {row["lead_id"]: row for row in rows}
            self.assertEqual("true", by_id["UW-001"]["qualified"])
            self.assertEqual("true", by_id["UW-001"]["accepting_outreach"])
            self.assertEqual("100", by_id["UW-001"]["applicable_max"])
            self.assertEqual("false", by_id["UW-002"]["qualified"])
            self.assertIn("posted within 2 hours", by_id["UW-002"]["qualification_notes"])
            self.assertEqual("true", by_id["VX-001"]["qualified"])
            self.assertEqual("65", by_id["VX-001"]["applicable_max"])
            self.assertEqual("unknown", by_id["PG-001"]["accepting_outreach"])
            self.assertIn("outreach availability: unknown", by_id["PG-001"]["qualification_notes"])
            self.assertEqual("false", by_id["PUBLIC-001"]["qualified"])
            self.assertEqual("false", by_id["PUBLIC-001"]["accepting_outreach"])
            self.assertIn("outreach is not explicitly closed", by_id["PUBLIC-001"]["qualification_notes"])
            self.assertNotIn("passed:  |", by_id["PUBLIC-001"]["qualification_notes"])

            upwork = (output_dir / "upwork_proposals.md").read_text("utf-8")
            self.assertIn("UW\\-001", upwork)
            self.assertNotIn("UW\\-002", upwork)
            self.assertIn("unsubmitted draft", upwork)
            domestic = (output_dir / "domestic_messages.md").read_text("utf-8")
            self.assertIn("VX\\-001", domestic)
            self.assertIn("PG\\-001", domestic)
            self.assertIn("未发送草稿", domestic)

            audit = [
                json.loads(line)
                for line in (output_dir / "audit.jsonl").read_text("utf-8").splitlines()
            ]
            self.assertEqual("offline", audit[0]["network_mode"])
            self.assertFalse(audit[-1]["external_action_performed"])
            self.assertNotIn("description", audit[0])

    def test_every_generated_upwork_proposal_is_120_to_160_words(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "leads"
            run_lead_assistant(SAMPLE, output_dir)
            text = (output_dir / "upwork_proposals.md").read_text("utf-8")
            proposal = text.split("- Status: unsubmitted draft; human review required\n\n", 1)[1]

            self.assertGreaterEqual(count_english_words(proposal), 120)
            self.assertLessEqual(count_english_words(proposal), 160)

    def test_upwork_proposal_range_uses_conservative_upper_bound(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "leads.csv"
            input_path.write_text(
                "lead_id,channel,title,description,age_hours,proposals,payment_verified\n"
                "U-1,upwork,PDF workflow,Document extraction workflow with audit evidence,1,15 to 20,yes\n",
                encoding="utf-8",
            )
            output_dir = root / "output"

            run_lead_assistant(input_path, output_dir)

            with (output_dir / "ranked_leads.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual("20", row["proposals"])
            self.assertEqual("false", row["qualified"])
            self.assertEqual("none", row["draft_type"])

    def test_published_at_requires_timezone_and_as_of_is_repeatable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "leads.csv"
            input_path.write_text(
                "lead_id,channel,title,description,published_at,proposals,payment_verified\n"
                "U-1,upwork,PDF workflow,Document automation with audit evidence,2026-08-26T08:00:00Z,4,yes\n",
                encoding="utf-8",
            )

            run_lead_assistant(
                input_path,
                root / "output",
                as_of="2026-08-26T09:30:00Z",
            )

            with (root / "output" / "ranked_leads.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual("1.50", row["age_hours"])
            self.assertEqual("true", row["qualified"])

    def test_output_csv_escapes_spreadsheet_formula_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "leads.csv"
            input_path.write_text(
                "lead_id,channel,title,description,age_hours,notes\n"
                "D-1,v2ex,PDF workflow,Document automation with audit evidence,1,=HYPERLINK(\"\"https://example.invalid\"\")\n",
                encoding="utf-8",
            )

            run_lead_assistant(input_path, root / "output")

            with (root / "output" / "ranked_leads.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                row = next(csv.DictReader(handle))
            self.assertTrue(row["notes"].startswith("'="))

    def test_rejects_missing_upwork_gate_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "leads.csv"
            input_path.write_text(
                "lead_id,channel,title,description,age_hours\n"
                "U-1,upwork,PDF workflow,Document automation with audit evidence,1\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(InputError, "needs proposals"):
                run_lead_assistant(input_path, Path(temp_dir) / "output")

    def test_rejects_non_finite_age(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "leads.csv"
            input_path.write_text(
                "lead_id,channel,title,description,age_hours\n"
                "D-1,v2ex,PDF workflow,Document automation with audit evidence,nan\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(InputError, "finite age_hours"):
                run_lead_assistant(input_path, Path(temp_dir) / "output")

    def test_explicitly_closed_outreach_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "leads.csv"
            input_path.write_text(
                "lead_id,channel,title,description,age_hours,accepting_outreach\n"
                "V-1,v2ex,PDF workflow,Document automation with audit evidence,1,closed\n",
                encoding="utf-8",
            )

            run_lead_assistant(input_path, root / "output")

            with (root / "output" / "ranked_leads.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual("false", row["qualified"])
            self.assertEqual("false", row["accepting_outreach"])
            self.assertIn("failed: outreach is not explicitly closed", row["qualification_notes"])

    def test_suppressed_lead_stays_ranked_but_never_generates_a_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            suppressions_path = root / "suppressions.csv"
            suppressions_path.write_text(
                "lead_id,reason,ignored_private_column\n"
                "VX-001,request explicitly closed,do not copy this\n",
                encoding="utf-8",
            )
            output_dir = root / "output"

            run_lead_assistant(
                SAMPLE,
                output_dir,
                suppressions_path=suppressions_path,
            )

            with (output_dir / "ranked_leads.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            row = next(row for row in rows if row["lead_id"] == "VX-001")
            self.assertEqual("false", row["qualified"])
            self.assertEqual("none", row["draft_type"])
            self.assertIn(
                "suppressed by operator-provided lead_id list",
                row["qualification_notes"],
            )
            self.assertIn(
                "suppression reason: request explicitly closed",
                row["qualification_notes"],
            )
            self.assertNotIn("VX\\-001", (output_dir / "domestic_messages.md").read_text("utf-8"))

            audit = [
                json.loads(line)
                for line in (output_dir / "audit.jsonl").read_text("utf-8").splitlines()
            ]
            suppressed_event = next(
                event for event in audit if event["event"] == "lead_suppressed"
            )
            self.assertEqual(
                {
                    "event",
                    "timestamp",
                    "lead_id",
                    "reason",
                },
                set(suppressed_event),
            )
            self.assertEqual("request explicitly closed", suppressed_event["reason"])
            self.assertNotIn("do not copy this", json.dumps(audit))
            self.assertEqual(1, audit[-1]["suppressed_count"])

    def test_cli_suppression_reason_cannot_become_a_spreadsheet_formula(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            suppressions_path = root / "suppressions.csv"
            suppressions_path.write_text(
                "lead_id,reason\n"
                'VX-001,"=HYPERLINK(""https://example.invalid"")"\n',
                encoding="utf-8",
            )
            output_dir = root / "output"

            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "leads",
                        str(SAMPLE),
                        "--output-dir",
                        str(output_dir),
                        "--suppressions",
                        str(suppressions_path),
                    ]
                )

            self.assertEqual(0, code)
            with (output_dir / "ranked_leads.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            row = next(row for row in rows if row["lead_id"] == "VX-001")
            self.assertFalse(row["qualification_notes"].lstrip().startswith("="))
            self.assertIn("=HYPERLINK", row["qualification_notes"])

    def test_rejects_suppression_csv_without_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            suppressions_path = root / "suppressions.csv"
            suppressions_path.write_text("lead_id\nVX-001\n", encoding="utf-8")

            with self.assertRaisesRegex(InputError, "missing required columns: reason"):
                run_lead_assistant(
                    SAMPLE,
                    root / "output",
                    suppressions_path=suppressions_path,
                )


if __name__ == "__main__":
    unittest.main()
