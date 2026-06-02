from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.clause import Clause, RiskFinding
from app.services.legal_kb_service import LegalKnowledgeBase, get_legal_kb
from app.services.legal_taxonomy import CLAUSE_DEFINITIONS


@dataclass(slots=True)
class VerificationCheckResult:
    check: str
    passed: bool
    detail: str


class VerificationService:
    """Deterministic verification checks for risk findings and chat answers."""

    missing_like_categories = {"missing_protection_risk", "recommended_review_gap"}
    generic_risk_categories = {
        "financial_risk",
        "termination_risk",
        "liability_risk",
        "security_deposit_risk",
        "other",
    }

    def __init__(self, kb: LegalKnowledgeBase | None = None) -> None:
        self.kb = kb or get_legal_kb()

    def verify_risk_finding(
        self,
        *,
        finding: RiskFinding,
        clause: Clause | None,
        contract_type: str,
    ) -> dict:
        checks = [
            self._risk_quote_check(finding),
            self._risk_page_check(finding=finding, clause=clause),
            self._risk_rule_check(
                finding=finding, clause=clause, contract_type=contract_type
            ),
        ]
        return self._finalize(checks)

    def verify_chat_answer(
        self,
        *,
        answer: str,
        sources: list[dict],
        intent: str,
        required_clause_types: list[str],
        citation_score: float,
        total_pages: int | None,
        confidence_label: str,
    ) -> dict:
        unsupported = answer.strip().lower() == "i could not find this information in the contract."
        if unsupported:
            checks = [
                VerificationCheckResult(
                    check="refusal_policy",
                    passed=True,
                    detail="Assistant used the strict unsupported-answer fallback.",
                ),
                VerificationCheckResult(
                    check="no_claim_without_sources",
                    passed=len(sources) == 0,
                    detail=(
                        "No evidence snippets returned with unsupported answer."
                        if len(sources) == 0
                        else "Unsupported answer should not include evidence snippets."
                    ),
                ),
                VerificationCheckResult(
                    check="confidence_consistency",
                    passed=confidence_label in {"not_enough_evidence", "low"},
                    detail=f"Confidence label is '{confidence_label}'.",
                ),
            ]
            return self._finalize(checks)

        checks = [
            self._chat_quote_check(sources=sources, citation_score=citation_score),
            self._chat_page_check(sources=sources, total_pages=total_pages),
            self._chat_rule_check(
                sources=sources,
                intent=intent,
                required_clause_types=required_clause_types,
            ),
        ]
        return self._finalize(checks)

    def _risk_quote_check(self, finding: RiskFinding) -> VerificationCheckResult:
        evidence = self._normalize_text(finding.evidence_text)
        if finding.risk_category in self.missing_like_categories:
            passed = "not found" in evidence or len(evidence) >= 24
            detail = (
                "Missing/recommended clause finding records absence evidence."
                if passed
                else "Missing/recommended finding lacks clear absence evidence text."
            )
            return VerificationCheckResult(
                check="quote_evidence",
                passed=passed,
                detail=detail,
            )

        passed = len(evidence) >= 45 and len(self._tokens(evidence)) >= 8
        return VerificationCheckResult(
            check="quote_evidence",
            passed=passed,
            detail=(
                "Finding includes a substantial evidence quote."
                if passed
                else "Evidence quote is too short or weak for reliable verification."
            ),
        )

    def _risk_page_check(
        self, *, finding: RiskFinding, clause: Clause | None
    ) -> VerificationCheckResult:
        page = finding.page_number
        if page is None or page <= 0:
            return VerificationCheckResult(
                check="page_citation",
                passed=False,
                detail="No valid source page was attached to this finding.",
            )

        if clause is None:
            return VerificationCheckResult(
                check="page_citation",
                passed=True,
                detail=f"Page citation exists (page {page}).",
            )

        passed = clause.page_start <= page <= clause.page_end
        return VerificationCheckResult(
            check="page_citation",
            passed=passed,
            detail=(
                f"Page {page} matches clause span {clause.page_start}-{clause.page_end}."
                if passed
                else f"Page {page} does not match clause span {clause.page_start}-{clause.page_end}."
            ),
        )

    def _risk_rule_check(
        self,
        *,
        finding: RiskFinding,
        clause: Clause | None,
        contract_type: str,
    ) -> VerificationCheckResult:
        expected = set(self.kb.expected_clauses(contract_type))
        recommended = set(self.kb.recommended_clauses(contract_type))

        if clause and clause.clause_type in CLAUSE_DEFINITIONS:
            if finding.risk_category.startswith(f"{clause.clause_type}_"):
                return VerificationCheckResult(
                    check="rule_alignment",
                    passed=True,
                    detail=f"Risk category aligns with clause type '{clause.clause_type}'.",
                )
            if clause.clause_type in expected or clause.clause_type in recommended:
                return VerificationCheckResult(
                    check="rule_alignment",
                    passed=True,
                    detail=f"Clause '{clause.clause_type}' is part of document playbook coverage.",
                )
            if finding.risk_category in self.generic_risk_categories:
                return VerificationCheckResult(
                    check="rule_alignment",
                    passed=True,
                    detail="Generic deterministic risk category accepted for this clause.",
                )

        inferred = self._extract_clause_type_from_summary(finding.summary)
        if inferred and (
            inferred in CLAUSE_DEFINITIONS
            or inferred in expected
            or inferred in recommended
        ):
            return VerificationCheckResult(
                check="rule_alignment",
                passed=True,
                detail=f"Finding references playbook clause '{inferred}'.",
            )

        return VerificationCheckResult(
            check="rule_alignment",
            passed=False,
            detail="Could not confidently map this finding to a valid clause/rule profile.",
        )

    def _chat_quote_check(
        self, *, sources: list[dict], citation_score: float
    ) -> VerificationCheckResult:
        has_sources = len(sources) > 0
        has_substance = all(
            len(self._normalize_text(str(source.get("evidence", "")))) >= 20
            for source in sources
        ) if has_sources else False
        passed = has_sources and has_substance and citation_score >= 0.72
        return VerificationCheckResult(
            check="quote_evidence",
            passed=passed,
            detail=(
                f"Evidence snippets are grounded (citation score {citation_score:.2f})."
                if passed
                else "Evidence snippets are missing, weak, or not sufficiently grounded."
            ),
        )

    def _chat_page_check(
        self, *, sources: list[dict], total_pages: int | None
    ) -> VerificationCheckResult:
        if not sources:
            return VerificationCheckResult(
                check="page_citation",
                passed=False,
                detail="No page citations were provided.",
            )

        def _page_ok(raw_page: object) -> bool:
            if not isinstance(raw_page, int) or raw_page <= 0:
                return False
            if total_pages is None:
                return True
            return raw_page <= total_pages

        passed = all(_page_ok(source.get("page")) for source in sources)
        return VerificationCheckResult(
            check="page_citation",
            passed=passed,
            detail=(
                "All evidence snippets include valid page citations."
                if passed
                else "One or more evidence snippets have invalid page citations."
            ),
        )

    def _chat_rule_check(
        self,
        *,
        sources: list[dict],
        intent: str,
        required_clause_types: list[str],
    ) -> VerificationCheckResult:
        if not required_clause_types:
            return VerificationCheckResult(
                check="rule_alignment",
                passed=True,
                detail=f"Intent '{intent}' does not require a strict clause-type match.",
            )

        required = {self._norm_clause(item) for item in required_clause_types}
        source_types = {self._norm_clause(str(item.get('clause_type', ''))) for item in sources}
        expanded_source_types = set(source_types)
        for source_type in list(source_types):
            if not source_type:
                continue
            expanded_source_types.update(self._norm_clause(alias) for alias in self.kb.aliases_for(source_type))

        passed = bool(required.intersection(expanded_source_types))
        return VerificationCheckResult(
            check="rule_alignment",
            passed=passed,
            detail=(
                "Answer evidence matches the required clause focus."
                if passed
                else "Evidence clause types do not match required clause focus."
            ),
        )

    @staticmethod
    def _extract_clause_type_from_summary(summary: str) -> str | None:
        if ":" not in summary:
            return None
        candidate = summary.split(":", 1)[1]
        candidate = re.sub(r"[^a-zA-Z0-9 _-]", " ", candidate).strip().lower()
        candidate = candidate.replace("-", "_").replace(" ", "_")
        return re.sub(r"_+", "_", candidate) or None

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(value.split()).strip().lower()

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return [token for token in re.findall(r"\w+", value.lower()) if len(token) > 2]

    @staticmethod
    def _norm_clause(value: str) -> str:
        return re.sub(r"_+", "_", value.strip().lower().replace("-", "_").replace(" ", "_"))

    @staticmethod
    def _finalize(checks: list[VerificationCheckResult]) -> dict:
        checks_passed = sum(1 for item in checks if item.passed)
        checks_total = len(checks)
        status = "verified" if checks_passed == checks_total else "needs_review"
        failed = [item.check for item in checks if not item.passed]
        reasons = [item.detail for item in checks if not item.passed]
        return {
            "status": status,
            "score": round(checks_passed / max(1, checks_total), 3),
            "checks_total": checks_total,
            "checks_passed": checks_passed,
            "failed_checks": failed,
            "reasons": reasons,
            "checks": [
                {"check": item.check, "passed": item.passed, "detail": item.detail}
                for item in checks
            ],
        }
