from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol


class FindingLike(Protocol):
    risk_category: str
    summary: str
    evidence_text: str
    confidence_score: float
    risk_score: int


@dataclass(slots=True)
class EvidenceValidation:
    action: str
    confidence_delta: float = 0.0
    score_delta: int = 0
    checks: list[dict[str, bool | str]] = field(default_factory=list)


class EvidenceValidator:
    """Pass/modify/drop validation for proposed risk findings."""

    placeholder_re = re.compile(r"_{3,}|\\[\\s*\\]|\\[●\\]|<\\s*>")

    def validate(self, finding: FindingLike) -> EvidenceValidation:
        text = " ".join((finding.evidence_text or "").split()).lower()
        checks: list[dict[str, bool | str]] = []

        has_evidence = len(text) >= 30
        checks.append({"check": "evidence_text_has_substance", "result": has_evidence})
        if not has_evidence and finding.risk_category != "missing_protection_risk":
            return EvidenceValidation(action="drop", checks=checks)

        if "auto_renewal" in finding.risk_category or "Auto-renewal" in finding.summary:
            positive = any(
                phrase in text
                for phrase in (
                    "automatically renew",
                    "renewed automatically",
                    "successive renewal terms unless",
                    "shall renew automatically",
                )
            )
            negative = any(
                phrase in text
                for phrase in (
                    "may be renewed",
                    "mutual consent",
                    "subject to approval",
                    "can be renewed",
                )
            )
            checks.append({"check": "auto_renewal_requires_automatic_language", "result": positive})
            checks.append({"check": "auto_renewal_negative_pattern_absent", "result": not negative})
            if not positive or negative:
                return EvidenceValidation(action="drop", checks=checks)

        confidence_delta = 0.0
        score_delta = 0
        if self.placeholder_re.search(finding.evidence_text or ""):
            confidence_delta -= 0.12
            score_delta += 4
            checks.append({"check": "placeholder_present", "result": True})
        if finding.risk_category == "missing_protection_risk":
            confidence_delta -= 0.18
            checks.append({"check": "missing_clause_confidence_penalty", "result": True})
        if finding.risk_score < 20 and finding.risk_category != "recommended_review_gap":
            return EvidenceValidation(action="drop", checks=checks)

        return EvidenceValidation(
            action="modify" if confidence_delta or score_delta else "pass",
            confidence_delta=confidence_delta,
            score_delta=score_delta,
            checks=checks,
        )
