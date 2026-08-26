import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from regulated_workflow.cli import main
from regulated_workflow.workflows import run_diff, run_extract


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = PROJECT_ROOT / "samples"


class WorkflowTests(unittest.TestCase):
    def test_extract_generates_review_artifacts_without_network(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "extract"
            with patch(
                "regulated_workflow.workflows.OpenAICompatibleAdapter.from_env",
                side_effect=AssertionError("default workflow attempted network setup"),
            ):
                paths = run_extract(SAMPLES / "new", output_dir)

            self.assertEqual(5, len(paths))
            self.assertEqual(
                {
                    "audit.jsonl",
                    "changes.json",
                    "evidence.json",
                    "review_queue.csv",
                    "summary.md",
                },
                {path.name for path in paths},
            )
            evidence = json.loads((output_dir / "evidence.json").read_text("utf-8"))
            self.assertTrue(evidence)
            self.assertTrue(all(item["review_status"] == "pending" for item in evidence))
            self.assertEqual(
                [], json.loads((output_dir / "changes.json").read_text("utf-8"))
            )
            self.assertFalse((output_dir / "llm_draft.md").exists())

            audit_records = [
                json.loads(line)
                for line in (output_dir / "audit.jsonl").read_text("utf-8").splitlines()
            ]
            self.assertEqual("offline", audit_records[0]["network_mode"])
            self.assertNotIn("quote", (output_dir / "audit.jsonl").read_text("utf-8"))

    def test_diff_flags_synthetic_regulated_changes_for_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "diff"
            paths = run_diff(SAMPLES / "old", SAMPLES / "new", output_dir)

            self.assertEqual(5, len(paths))
            changes = json.loads((output_dir / "changes.json").read_text("utf-8"))
            self.assertGreaterEqual(len(changes), 10)
            self.assertTrue(any(item["risk_level"] == "high" for item in changes))
            self.assertTrue(
                any("Retention Years" in item["field"] for item in changes)
            )
            self.assertTrue(all(item["review_status"] == "pending" for item in changes))

            with (output_dir / "review_queue.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                queue = list(csv.DictReader(handle))
            self.assertEqual(len(changes), len(queue))
            self.assertTrue(all(row["record_type"] == "change" for row in queue))

            summary = (output_dir / "summary.md").read_text("utf-8")
            self.assertIn("not regulatory judgments", summary)
            self.assertIn("human reviewer", summary)

    def test_cli_reports_user_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            code = main(
                [
                    "extract",
                    str(Path(temp_dir) / "missing"),
                    "--output-dir",
                    str(Path(temp_dir) / "output"),
                ]
            )
            self.assertEqual(2, code)

    def test_review_csv_escapes_spreadsheet_formulas(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "untrusted.json"
            input_path.write_text(
                '{"owner": "=HYPERLINK(\\"https://example.invalid\\", \\"click\\")"}',
                encoding="utf-8",
            )
            output_dir = root / "output"

            run_extract(input_path, output_dir)

            with (output_dir / "review_queue.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(rows[0]["value"].startswith("'="))

    def test_diff_aligns_differently_named_direct_file_versions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_path = root / "policy-v1.md"
            new_path = root / "policy-v2.md"
            old_path.write_text("Retention Years: 5\n", encoding="utf-8")
            new_path.write_text("Retention Years: 7\n", encoding="utf-8")
            output_dir = root / "output"

            run_diff(old_path, new_path, output_dir)

            changes = json.loads((output_dir / "changes.json").read_text("utf-8"))
            self.assertEqual(1, len(changes))
            self.assertEqual(
                "policy-v1.md -> policy-v2.md::Retention Years",
                changes[0]["field"],
            )
            self.assertEqual("5", changes[0]["old_value"])
            self.assertEqual("7", changes[0]["new_value"])

            evidence = json.loads((output_dir / "evidence.json").read_text("utf-8"))
            self.assertEqual(
                "policy-v1.md -> policy-v2.md", evidence[0]["source_id"]
            )
            audit = [
                json.loads(line)
                for line in (output_dir / "audit.jsonl").read_text("utf-8").splitlines()
            ]
            parsed_sources = {
                (event["input_role"], event["source_id"])
                for event in audit
                if event["event"] == "document_parsed"
            }
            self.assertEqual(
                {("old", "policy-v1.md"), ("new", "policy-v2.md")},
                parsed_sources,
            )


if __name__ == "__main__":
    unittest.main()
