from __future__ import annotations

import re
from typing import Protocol, TypeVar


class MutableFindingLike(Protocol):
    risk_category: str
    risk_level: str
    risk_score: int
    summary: str
    why_risky: str
    suggested_question: str
    evidence_text: str
    page_number: int | None
    confidence_score: float


FindingT = TypeVar("FindingT", bound=MutableFindingLike)


class RiskPostProcessor:
    """Groups duplicate/overlapping risks after evidence validation."""

    group_rules: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("payment_uncertainty", ("payment", "commercial_terms")),
        ("termination_uncertainty", ("termination", "forfeiture", "immediate_acceleration")),
        ("liability_exposure", ("liability", "indemnity", "uncapped")),
        ("data_privacy_exposure", ("data_privacy", "data", "privacy")),
    )

    def process(self, findings: list[FindingT]) -> list[FindingT]:
        output: list[FindingT] = []
        seen: set[tuple[str, int | None, str]] = set()

        for finding in sorted(findings, key=lambda item: item.risk_score, reverse=True):
            group = self._group_for(finding)
            key = (group, finding.page_number, self._normalize_evidence(finding.evidence_text))
            if key in seen:
                continue
            seen.add(key)
            output.append(finding)

        return output

    def _group_for(self, finding: MutableFindingLike) -> str:
        haystack = f"{finding.risk_category} {finding.summary}".lower()
        for group, markers in self.group_rules:
            if any(marker in haystack for marker in markers):
                return group
        return re.sub(r"[^a-z0-9]+", "_", finding.risk_category.lower()).strip("_")

    @staticmethod
    def _normalize_evidence(evidence: str) -> str:
        normalized = " ".join(evidence.lower().split())
        return normalized[:180]
