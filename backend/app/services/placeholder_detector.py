from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class PlaceholderIssue:
    field: str
    evidence_text: str
    page_number: int | None
    severity: str
    confidence_score: float


class PlaceholderDetector:
    """Finds unfilled template blanks as a separate issue type."""

    blank_re = re.compile(
        r"(?P<label>[A-Za-z][A-Za-z /()%-]{0,50})?\s*(?:₹|rs\.?|inr|amount|date|rate|interest|name|address|term|days|months)?\s*(?P<blank>_{3,}|\.{5,}|\[\s*\]|\[●\]|<\s*>)",
        re.IGNORECASE,
    )
    field_patterns: tuple[tuple[str, tuple[str, ...], str], ...] = (
        ("loan amount", ("loan", "amount", "principal", "inr", "rs", "₹"), "medium"),
        ("interest rate", ("interest", "rate", "%"), "medium"),
        ("payment amount", ("fee", "payment", "rent", "charges", "price"), "medium"),
        ("date", ("date", "day", "month", "year"), "low"),
        (
            "party name/address",
            ("name", "address", "party", "borrower", "tenant", "client"),
            "medium",
        ),
        ("notice period", ("notice", "days", "months"), "low"),
    )

    def detect_pages(self, pages: list[tuple[int, str]]) -> list[PlaceholderIssue]:
        issues: list[PlaceholderIssue] = []
        for page_number, text in pages:
            for match in self.blank_re.finditer(text):
                start = max(0, match.start() - 80)
                end = min(len(text), match.end() + 100)
                evidence = " ".join(text[start:end].split())
                if len(evidence) < 6:
                    continue
                field, severity = self._classify_field(evidence)
                issues.append(
                    PlaceholderIssue(
                        field=field,
                        evidence_text=evidence[:500],
                        page_number=page_number,
                        severity=severity,
                        confidence_score=0.82,
                    )
                )
        return self._dedupe(issues)

    def _classify_field(self, evidence: str) -> tuple[str, str]:
        lowered = evidence.lower()
        for field, keywords, severity in self.field_patterns:
            if any(keyword in lowered for keyword in keywords):
                return field, severity
        return "unfilled field", "low"

    @staticmethod
    def _dedupe(issues: list[PlaceholderIssue]) -> list[PlaceholderIssue]:
        output: list[PlaceholderIssue] = []
        seen: set[tuple[str, int | None, str]] = set()
        for issue in issues:
            key = (issue.field, issue.page_number, issue.evidence_text[:80].lower())
            if key in seen:
                continue
            seen.add(key)
            output.append(issue)
        return output[:20]
