"""Focused, source-cited issue spotting for property title reports.

This deliberately does not infer that a historical mortgage remains active or
that a pending case has an adverse outcome. It surfaces what the report says
and asks for current supporting evidence.
"""

from __future__ import annotations

import re

from app.services.risk_engine import RiskAnalysisResult, RiskFindingDraft
from app.services.text_cleaner import CleanedPage


class TitleReportAnalyzer:
    def analyze(self, pages: list[CleanedPage]) -> RiskAnalysisResult:
        findings: list[RiskFindingDraft] = []

        for page in pages:
            text = " ".join(page.cleaned_text.split())
            lowered = text.lower()

            if (
                "annexure b" in lowered
                and "encumbrance" in lowered
                and "project finance" in lowered
                and ("mortgaged" in lowered or "charged" in lowered)
            ):
                findings.append(self._finding(
                    page, text, "project finance", 72,
                    "Project-finance charges are listed in the encumbrance annexure.",
                    "The report describes mortgages and charges over project land or assets. "
                    "It does not establish whether those charges have since been discharged.",
                    "Which charges still affect this property, and can the lenders provide "
                    "current discharge or no-objection evidence?",
                    "project_finance_charge_risk",
                ))

            title_opinion = re.search(
                r"(clear(?:,| and)?\s+marketable).{0,250}(?:save and except|subject to)",
                lowered,
            )
            if title_opinion:
                findings.append(self._finding(
                    page, text, title_opinion.group(1), 64,
                    "The clear-title opinion is expressly qualified by exceptions.",
                    "The advocate's positive title opinion is subject to stated encumbrances "
                    "and pending litigation; it should not be read as an unconditional clearance.",
                    "Which title-opinion exceptions remain open, and what current "
                    "records resolve each one?",
                    "qualified_title_opinion_risk",
                ))

            case_number = re.search(r"\bR\.?\s*C\.?\s*S\.?\s*No\.?", text, re.I)
            if case_number and (
                "civil suit" in lowered or "litigation" in lowered
            ):
                findings.append(self._finding(
                    page, text, case_number.group(0), 62,
                    "A civil case concerning the property is reported as pending.",
                    "The report identifies a property-related civil suit. Its statement that no "
                    "adverse order had been passed is dated, not proof that the case is closed.",
                    "What is the current case status and does any order or settlement "
                    "affect the property?",
                    "pending_litigation_risk",
                ))

            if "as is where is basis" in lowered and "encumbrances and litigations" in lowered:
                findings.append(self._finding(
                    page, text, "encumbrances and litigations", 56,
                    "The historical bank auction sale included encumbrances and litigation.",
                    "The sale-chain evidence records an as-is auction. This is a historical "
                    "title matter; the report alone does not show which inherited issues remain.",
                    "Does the sale certificate and subsequent title chain resolve the "
                    "auction's listed encumbrances and litigation?",
                    "auction_encumbrance_risk",
                ))

            if "subject to compliance" in lowered and "master layout" in lowered:
                findings.append(self._finding(
                    page, text, "subject to compliance", 46,
                    "The title conclusion depends on compliance with layout conditions.",
                    "The report expressly conditions its conclusion on compliance with a "
                    "named master-layout approval and removal of relevant remarks or encumbrances.",
                    "Which approval conditions and revenue-record remarks remain, and "
                    "what evidence shows compliance?",
                    "approval_conditions_risk",
                ))

        # Repeated annexure references do not create separate independent risks.
        unique: dict[str, RiskFindingDraft] = {}
        for finding in findings:
            unique.setdefault(finding.risk_category, finding)
        ordered = sorted(unique.values(), key=lambda item: item.risk_score, reverse=True)
        if ordered:
            score = round(sum(item.risk_score for item in ordered[:3]) / min(3, len(ordered)))
        else:
            score = 0
        level = "high" if score >= 51 else "medium" if score >= 26 else "low"
        return RiskAnalysisResult(
            findings=ordered,
            missing_clauses=[],
            overall_risk_score=score,
            overall_risk_level=level,
        )

    @staticmethod
    def _finding(
        page: CleanedPage,
        text: str,
        anchor: str,
        score: int,
        summary: str,
        why_risky: str,
        question: str,
        category: str,
    ) -> RiskFindingDraft:
        position = text.lower().find(anchor.lower())
        if position < 0:
            position = 0
        start = max(0, position - 130)
        end = min(len(text), position + 570)
        excerpt = text[start:end].strip()
        if start:
            excerpt = excerpt.partition(" ")[2]
        if end < len(text):
            excerpt = excerpt.rpartition(" ")[0]
        return RiskFindingDraft(
            clause_id=None,
            risk_category=category,
            risk_level="high" if score >= 51 else "medium" if score >= 26 else "low",
            risk_score=score,
            summary=summary,
            why_risky=why_risky,
            suggested_question=question,
            evidence_text=excerpt,
            page_number=page.page_number,
            confidence_score=0.9,
        )
