from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clause import Clause, RiskFinding
from app.models.document import Document, DocumentPage
from app.services.clause_normalizer import ClauseNormalizer
from app.services.document_classifier import DocumentClassifier
from app.services.legal_kb_service import LegalKnowledgeBase, get_legal_kb
from app.services.legal_taxonomy import (
    CLAUSE_DEFINITIONS,
    CONTRACT_TYPE_LABELS,
    DOCUMENT_ANALYSIS_PROFILES,
    EXPECTED_CLAUSES_BY_CONTRACT,
    RECOMMENDED_CLAUSES_BY_CONTRACT,
)
from app.services.party_role_extractor import PartyRoleExtractor
from app.services.text_cleaner import CleanedPage
from app.services.verification_service import VerificationService


class AnalysisService:
    """Aggregates clause and deterministic risk results for analysis responses."""

    def __init__(self, kb: LegalKnowledgeBase | None = None) -> None:
        self.kb = kb or get_legal_kb()
        self.normalizer = ClauseNormalizer(self.kb)
        self.document_classifier = DocumentClassifier()
        self.party_extractor = PartyRoleExtractor()
        self.verifier = VerificationService(self.kb)

    async def get_analysis(
        self, session: AsyncSession, document_id: str, *, owner_user_id: str | None = None
    ) -> dict:
        document = await session.get(Document, document_id)
        if document is None or (
            owner_user_id is not None and document.owner_user_id != owner_user_id
        ):
            raise ValueError("Document not found")

        clause_rows = await session.execute(select(Clause).where(Clause.document_id == document_id))
        clauses = clause_rows.scalars().all()
        page_rows = await session.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number.asc())
        )
        pages = page_rows.scalars().all()
        full_text = "\n".join(page.cleaned_text for page in pages)
        page_inputs = [
            CleanedPage(
                page_number=page.page_number, raw_text=page.raw_text, cleaned_text=page.cleaned_text
            )
            for page in pages
        ]
        document_classification = self.document_classifier.classify(page_inputs)
        party_roles = self.party_extractor.extract(full_text)

        finding_rows = await session.execute(
            select(RiskFinding)
            .where(RiskFinding.document_id == document_id)
            .order_by(RiskFinding.risk_score.desc())
        )
        findings = finding_rows.scalars().all()
        unique_findings = self._dedupe_findings(findings)

        clause_map = {clause.id: clause for clause in clauses}
        missing_clauses = self._missing_clauses(document.contract_type or "unknown", clauses)
        review_clauses = self._review_clauses(document.contract_type or "unknown", clauses)

        overall_risk_score = self._overall_score(unique_findings)
        overall_risk_level = self._risk_level(overall_risk_score)

        contract_type = document.contract_type or "unknown"
        top_risks: list[dict] = []
        verified_count = 0
        needs_review_count = 0
        for finding in unique_findings[:8]:
            clause = clause_map.get(finding.clause_id) if finding.clause_id else None
            clause_type = (
                clause.clause_type if clause else self._infer_clause_type_from_finding(finding)
            )
            page = finding.page_number or (clause.page_start if clause else 1)
            verification = self.verifier.verify_risk_finding(
                finding=finding,
                clause=clause,
                contract_type=contract_type,
            )
            if verification["status"] == "verified":
                verified_count += 1
            else:
                needs_review_count += 1

            top_risks.append(
                {
                    "finding_id": finding.id,
                    "clause_type": clause_type,
                    "clause_id": clause.id if clause else None,
                    "risk_level": finding.risk_level,
                    "risk_score": finding.risk_score,
                    "risk_category": finding.risk_category,
                    "summary": finding.summary,
                    "why_risky": finding.why_risky,
                    "suggested_question": finding.suggested_question,
                    "page": page,
                    "evidence": finding.evidence_text,
                    "plain_language": self._plain_language(finding.summary, finding.why_risky),
                    "verification": verification,
                }
            )

        risk_counts = self._risk_counts(unique_findings)
        profile = self.kb.playbook(contract_type) or DOCUMENT_ANALYSIS_PROFILES.get(
            contract_type, {}
        )
        present_clause_types = self._present_clause_types(clauses)
        return {
            "contract_type": contract_type,
            "contract_type_label": CONTRACT_TYPE_LABELS.get(
                contract_type,
                str(profile.get("display_name") or self._pretty_label(contract_type)),
            ),
            "document_profile": {
                "purpose": str(
                    profile.get("purpose", "Document purpose could not be inferred confidently.")
                ),
                "likely_user_role": str(profile.get("likely_user_role", "Unknown")),
                "stronger_party": str(profile.get("stronger_party", "Unknown")),
                "detected_parties": [party.name for party in party_roles]
                or self._extract_parties(full_text),
                "party_roles": [
                    {
                        "name": party.name,
                        "role": party.role,
                        "side": party.side,
                        "is_placeholder": party.is_placeholder,
                    }
                    for party in party_roles
                ],
                "governing_law": self._extract_governing_law(full_text),
            },
            "document_classification": {
                "primary_document_type": document_classification.primary_document_type,
                "secondary_document_types": document_classification.secondary_document_types,
                "is_template": document_classification.is_template,
                "is_executed_agreement": document_classification.is_executed_agreement,
                "is_collection_or_handbook": document_classification.is_collection_or_handbook,
                "contains_multiple_document_types": document_classification.contains_multiple_document_types,
                "confidence_score": document_classification.confidence_score,
                "sections": [
                    {
                        "document_type": section.document_type,
                        "title": section.title,
                        "page_start": section.page_start,
                        "page_end": section.page_end,
                        "confidence_score": section.confidence_score,
                    }
                    for section in document_classification.sections
                ],
            },
            "overall_risk_level": overall_risk_level,
            "overall_risk_score": overall_risk_score,
            "risk_summary": self._risk_summary(overall_risk_level, overall_risk_score, top_risks),
            "risk_counts": risk_counts,
            "missing_clauses": missing_clauses,
            "review_clauses": review_clauses,
            "false_positive_checks": self._false_positive_checks(contract_type, clauses),
            "review_focus": self.kb.review_focus(contract_type),
            "cuad_coverage": self._cuad_coverage(clauses),
            "jurisdiction_warnings": self.kb.jurisdiction_warnings(
                contract_type=contract_type,
                present_clause_types=present_clause_types,
                full_text=full_text,
            ),
            "benchmark_notes": self.kb.benchmark_notes(contract_type),
            "final_verdict": self._final_verdict(overall_risk_level, overall_risk_score, top_risks),
            "verification_summary": {
                "verified_count": verified_count,
                "needs_review_count": needs_review_count,
                "verification_rate": round(
                    verified_count / max(1, verified_count + needs_review_count), 3
                ),
            },
            "top_risks": top_risks,
            "extraction_health": {
                "clauses_found": len(clauses),
                "risks_found": len(findings),
                "source_pages": sorted(
                    {
                        int(finding.page_number)
                        for finding in findings
                        if finding.page_number is not None and int(finding.page_number) > 0
                    }
                ),
                "note": self._extraction_note(len(clauses), len(findings)),
            },
        }

    def _cuad_coverage(self, clauses: list[Clause]) -> dict:
        metadata = self.kb.cuad_metadata()
        mapped_types = sorted(
            {
                clause.clause_type
                for clause in clauses
                if self.kb.cuad_labels_for(clause.clause_type)
            }
        )
        return {
            "enabled": bool(metadata),
            "source": metadata.get("source", "theatticusproject/cuad"),
            "license": metadata.get("license", "CC BY 4.0"),
            "contract_count": int(metadata.get("contract_count", 0) or 0),
            "cuad_label_count": int(metadata.get("cuad_label_count", 0) or 0),
            "positive_answer_count": int(metadata.get("positive_answer_count", 0) or 0),
            "mapped_clause_types_detected": mapped_types,
        }

    def _missing_clauses(self, contract_type: str, clauses: list[Clause]) -> list[str]:
        expected = tuple(
            self.kb.expected_clauses(contract_type)
        ) or EXPECTED_CLAUSES_BY_CONTRACT.get(contract_type, ())
        if not expected:
            return []

        present = self._present_clause_types(clauses)
        return [clause_type for clause_type in expected if clause_type not in present]

    @staticmethod
    def _dedupe_findings(findings: list[RiskFinding]) -> list[RiskFinding]:
        output: list[RiskFinding] = []
        seen: set[tuple[str, str]] = set()
        for finding in findings:
            key = (finding.risk_category, " ".join(finding.summary.lower().split()))
            if key in seen:
                continue
            seen.add(key)
            output.append(finding)
        return output

    def _review_clauses(self, contract_type: str, clauses: list[Clause]) -> list[str]:
        recommended = tuple(
            self.kb.recommended_clauses(contract_type)
        ) or RECOMMENDED_CLAUSES_BY_CONTRACT.get(contract_type, ())
        if not recommended:
            return []

        present = self._present_clause_types(clauses)
        required = set(EXPECTED_CLAUSES_BY_CONTRACT.get(contract_type, ()))
        return [
            clause_type
            for clause_type in recommended
            if clause_type not in present and clause_type not in required
        ]

    def _overall_score(self, findings: list[RiskFinding]) -> int:
        material_findings = [
            finding for finding in findings if finding.risk_category != "recommended_review_gap"
        ]
        if not material_findings:
            return 18

        top_scores = [finding.risk_score for finding in material_findings[:8]]
        mean_top = sum(top_scores) / len(top_scores)
        amplification = min(12.0, len(material_findings) * 1.4)
        score = int(round(min(100.0, mean_top + amplification)))
        return max(0, score)

    @staticmethod
    def _risk_level(score: int) -> str:
        if score >= 76:
            return "critical"
        if score >= 51:
            return "high"
        if score >= 26:
            return "medium"
        return "low"

    @staticmethod
    def _infer_clause_type_from_finding(finding: RiskFinding) -> str:
        if finding.risk_category == "missing_protection_risk":
            if ":" in finding.summary:
                return finding.summary.split(":", 1)[1].strip(" .").replace(" ", "_")
            return "missing_clause"
        if finding.risk_category == "recommended_review_gap":
            if ":" in finding.summary:
                return finding.summary.split(":", 1)[1].strip(" .").replace(" ", "_")
            return "review_item"
        return "other"

    @staticmethod
    def _risk_counts(findings: list[RiskFinding]) -> dict[str, int]:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for finding in findings:
            if finding.risk_level in counts:
                counts[finding.risk_level] += 1
        return counts

    def _present_clause_types(self, clauses: list[Clause]) -> set[str]:
        present = {clause.clause_type for clause in clauses}
        clause_texts = [
            (clause.clause_title, clause.normalized_text or clause.clause_text.lower())
            for clause in clauses
        ]
        present.update(self.normalizer.present_clause_types(clause_texts))
        corpus = "\n".join(f"{title}\n{text}" for title, text in clause_texts).lower()

        for clause_type, definition in CLAUSE_DEFINITIONS.items():
            if clause_type in present:
                continue
            keywords = definition["keywords"]
            keyword_list = (keywords,) if isinstance(keywords, str) else keywords
            alias_list = tuple(self.kb.aliases_for(clause_type))
            matched = [
                keyword
                for keyword in (*keyword_list, *alias_list)
                if self._phrase_in_text(corpus, str(keyword).lower())
            ]
            if any(" " in keyword for keyword in matched) or len(matched) >= 2:
                present.add(clause_type)

        return present

    def _false_positive_checks(self, contract_type: str, clauses: list[Clause]) -> list[str]:
        present = self._present_clause_types(clauses)
        checks = [
            f"Checklist selected for {self._pretty_label(contract_type)}, not a generic freelance template.",
            "Missing-clause checks also scan equivalent wording in extracted text, schedules, and annexure-like sections.",
        ]
        checks.extend(self.kb.false_positive_guardrails(contract_type))
        if "payment" in present:
            checks.append(
                "Payment/fees were treated as present where billing, rent, charges, rates, or schedules appear."
            )
        if "confidentiality" in present:
            checks.append(
                "Confidentiality was treated as present where secrecy or data-protection wording appears."
            )
        if contract_type not in {
            "freelance_contract",
            "service_agreement",
            "software_saas_agreement",
        }:
            checks.append(
                "IP ownership was not treated as a core risk unless this document type normally needs it."
            )
        return checks

    @staticmethod
    def _final_verdict(level: str, score: int, top_risks: list[dict]) -> str:
        if not top_risks:
            return "No major deterministic risk was found, but this should still receive human review before signing."
        if level == "critical":
            return "Do not sign without legal review; at least one term creates severe exposure."
        if level == "high":
            return "Negotiate or clarify the top risks before signing."
        if level == "medium":
            return f"Usable with caution. Review the main issues before signing; current score is {score}/100."
        return (
            "Generally lower-risk based on extracted text, with routine review still recommended."
        )

    @staticmethod
    def _phrase_in_text(text: str, phrase: str) -> bool:
        return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text))

    @staticmethod
    def _extract_parties(full_text: str) -> list[str]:
        text = " ".join(full_text.split())[:6000]
        patterns = (
            r"\bbetween\s+(.{3,160}?)\s+and\s+(.{3,160}?)(?:\.|,|\(|;|\bwhereas\b)",
            r"\bby and between\s+(.{3,160}?)\s+and\s+(.{3,160}?)(?:\.|,|\(|;|\bwhereas\b)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            parties = [
                AnalysisService._clean_party_name(match.group(1)),
                AnalysisService._clean_party_name(match.group(2)),
            ]
            parties = [party for party in parties if 2 <= len(party) <= 120]
            if len(parties) == 2:
                return parties
        return []

    @staticmethod
    def _extract_governing_law(full_text: str) -> str | None:
        text = " ".join(full_text.split())[:12000]
        patterns = (
            r"governed by(?: and construed in accordance with)?(?: the)? laws of ([^.;]{3,100})",
            r"courts of ([^.;]{3,100}) shall have jurisdiction",
            r"subject to (?:the )?jurisdiction of ([^.;]{3,100})",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return AnalysisService._normalize_spaces(match.group(1)).strip(" ,")
        return None

    @staticmethod
    def _clean_party_name(value: str) -> str:
        cleaned = re.sub(
            r"\s+(?:hereinafter|hereafter|referred to as)\b.*$", "", value, flags=re.IGNORECASE
        )
        cleaned = re.sub(r"^[,:;\s]+|[,:;\s]+$", "", cleaned)
        return AnalysisService._normalize_spaces(cleaned)

    @staticmethod
    def _normalize_spaces(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def _plain_language(summary: str, why_risky: str) -> str:
        summary_text = " ".join(summary.split()).strip()
        why_text = " ".join(why_risky.replace("Risk signals:", "").split()).strip()
        if why_text:
            return f"{summary_text} Main concern: {why_text}"
        return summary_text

    @staticmethod
    def _risk_summary(level: str, score: int, top_risks: list[dict]) -> str:
        if not top_risks:
            return (
                "No high-confidence risk was found in the extracted clauses. "
                "A human review is still recommended before signing."
            )

        lead = top_risks[0]
        return (
            f"This document is currently rated {level} risk ({score}/100). "
            f"The biggest item to review is {lead['summary'].rstrip('.')}, "
            f"shown on page {lead['page']}."
        )

    @staticmethod
    def _extraction_note(clause_count: int, finding_count: int) -> str:
        if clause_count < 4:
            return "Low extraction coverage. Review the source document carefully."
        if finding_count == 0:
            return (
                "No deterministic risks were found; this does not mean the contract is risk-free."
            )
        return "Analysis is based on extracted clauses and cited source pages."

    @staticmethod
    def _pretty_label(value: str) -> str:
        return value.replace("_", " ").title()
