import unittest

from regulated_workflow.models import ChangeItem, EvidenceItem


class EvidenceItemTests(unittest.TestCase):
    def test_rejects_invalid_confidence(self):
        with self.assertRaises(ValueError):
            EvidenceItem(
                source_id="policy.md",
                page=1,
                quote="Status: Active",
                field="Status",
                value="Active",
                confidence=1.1,
            )

    def test_serializes_required_fields(self):
        item = ChangeItem(
            field="policy.md::Retention Years",
            old_value="5",
            new_value="7",
            risk_level="high",
            rationale="Value changed; human review required.",
        )
        self.assertEqual("pending", item.to_dict()["review_status"])


if __name__ == "__main__":
    unittest.main()
