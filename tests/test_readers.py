import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from regulated_workflow.errors import InputError, OptionalDependencyError
from regulated_workflow.readers import read_documents


class ReaderTests(unittest.TestCase):
    def test_reads_all_offline_text_formats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "policy.md").write_text("Status: Active\n", encoding="utf-8")
            (root / "notes.txt").write_text("Owner: Quality\n", encoding="utf-8")
            (root / "controls.csv").write_text(
                "Control,Threshold\nC-1,5\n", encoding="utf-8"
            )
            (root / "registry.json").write_text(
                '{"release": {"approved": false}}', encoding="utf-8"
            )

            documents = read_documents(root)

            self.assertEqual(4, len(documents))
            fields = {
                item.field for document in documents for item in document.evidence
            }
            self.assertIn("Status", fields)
            self.assertIn("row[1].Threshold", fields)
            self.assertIn("release.approved", fields)

    def test_malformed_json_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(InputError, "line 1 column 2"):
                read_documents(path)

    def test_pdf_without_optional_dependency_has_install_hint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.pdf"
            path.write_bytes(b"not-a-real-pdf")
            with patch(
                "regulated_workflow.readers.import_module",
                side_effect=ModuleNotFoundError("pypdf"),
            ):
                with self.assertRaisesRegex(OptionalDependencyError, "optional dependency"):
                    read_documents(path)


if __name__ == "__main__":
    unittest.main()
