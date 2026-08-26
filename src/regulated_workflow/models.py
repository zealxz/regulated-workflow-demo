from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


_REVIEW_STATUSES = {"pending", "approved", "rejected"}
_RISK_LEVELS = {"low", "medium", "high"}


@dataclass(frozen=True)
class EvidenceItem:
    source_id: str
    page: int
    quote: str
    field: str
    value: str
    confidence: float
    review_status: str = "pending"

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if self.page < 1:
            raise ValueError("page must be at least 1")
        if not self.field.strip():
            raise ValueError("field must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.review_status not in _REVIEW_STATUSES:
            raise ValueError("unsupported review_status: %s" % self.review_status)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChangeItem:
    field: str
    old_value: str
    new_value: str
    risk_level: str
    rationale: str
    review_status: str = "pending"

    def __post_init__(self) -> None:
        if not self.field.strip():
            raise ValueError("field must not be empty")
        if self.risk_level not in _RISK_LEVELS:
            raise ValueError("unsupported risk_level: %s" % self.risk_level)
        if not self.rationale.strip():
            raise ValueError("rationale must not be empty")
        if self.review_status not in _REVIEW_STATUSES:
            raise ValueError("unsupported review_status: %s" % self.review_status)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
