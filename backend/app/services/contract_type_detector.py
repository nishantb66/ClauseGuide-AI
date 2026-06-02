from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.legal_taxonomy import CONTRACT_TYPE_KEYWORDS


@dataclass(slots=True)
class ContractTypeResult:
    contract_type: str
    confidence_score: float
    evidence_keywords: list[str]


class ContractTypeDetector:
    """Lightweight contract-type detector based on phrase matching."""

    _token_re = re.compile(r"\w+")

    def detect(self, full_text: str) -> ContractTypeResult:
        text = " ".join(full_text.lower().split())
        if not text:
            return ContractTypeResult(contract_type="unknown", confidence_score=0.0, evidence_keywords=[])

        scores: dict[str, float] = {}
        evidence: dict[str, list[str]] = {}

        for contract_type, keywords in CONTRACT_TYPE_KEYWORDS.items():
            score = 0.0
            matched_keywords: list[str] = []
            for keyword in keywords:
                if keyword in text:
                    weight = 1.0 + (len(keyword.split()) - 1) * 0.2
                    if keyword in {
                        "legal services agreement",
                        "law firm",
                        "service bond",
                        "rental agreement",
                        "security deposit",
                        "empanelment",
                        "tender",
                        "request for proposal",
                        "blacklisting",
                        "debarment",
                        "software",
                        "saas",
                        "service level agreement",
                    }:
                        weight += 0.55
                    score += weight
                    matched_keywords.append(keyword)
            scores[contract_type] = score
            evidence[contract_type] = matched_keywords

        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        if best_score <= 1.0:
            return ContractTypeResult(contract_type="unknown", confidence_score=0.2, evidence_keywords=[])

        total_score = sum(scores.values())
        confidence = best_score / total_score if total_score > 0 else 0.0

        # Small boosts for common multi-signal combinations.
        if best_type == "employment_bond" and {"service bond", "bond period"}.intersection(
            evidence[best_type]
        ):
            confidence += 0.08
        if best_type == "rental_agreement" and {"landlord", "tenant"}.issubset(
            set(evidence[best_type])
        ):
            confidence += 0.08
        if best_type == "legal_services_agreement" and {
            "law firm",
            "legal services",
        }.issubset(set(evidence[best_type])):
            confidence += 0.12
        if best_type == "government_empanelment" and {
            "empanelment",
            "authority",
        }.intersection(set(evidence[best_type])):
            confidence += 0.12
        if best_type == "software_saas_agreement" and {
            "software",
            "data protection",
        }.intersection(set(evidence[best_type])):
            confidence += 0.1

        # Guard against broad "client/services" language overpowering specialized document types.
        if best_type == "freelance_contract":
            specialized_types = (
                "government_empanelment",
                "legal_services_agreement",
                "software_saas_agreement",
            )
            specialized_best = max(specialized_types, key=lambda item: scores[item])
            if scores[specialized_best] >= best_score * 0.72 and scores[specialized_best] >= 2.2:
                best_type = specialized_best
                best_score = scores[best_type]
                confidence = min(0.95, (best_score / max(1.0, total_score)) + 0.08)

        confidence = max(0.0, min(1.0, confidence))
        return ContractTypeResult(
            contract_type=best_type,
            confidence_score=confidence,
            evidence_keywords=evidence[best_type][:6],
        )
