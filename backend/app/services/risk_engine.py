from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.clause_normalizer import ClauseNormalizer
from app.services.evidence_validator import EvidenceValidator
from app.services.legal_kb_service import LegalKnowledgeBase, get_legal_kb
from app.services.legal_taxonomy import (
    CLAUSE_DEFINITIONS,
    DOCUMENT_ANALYSIS_PROFILES,
    EXPECTED_CLAUSES_BY_CONTRACT,
    RECOMMENDED_CLAUSES_BY_CONTRACT,
    RISK_LEVEL_SCORES,
)
from app.services.risk_post_processor import RiskPostProcessor
from app.services.universal_risk_trigger_engine import UniversalRiskTriggerEngine


@dataclass(slots=True)
class ClauseRiskInput:
    id: int | None
    clause_type: str
    clause_title: str
    clause_text: str
    normalized_text: str
    page_start: int


@dataclass(slots=True)
class RiskFindingDraft:
    clause_id: int | None
    risk_category: str
    risk_level: str
    risk_score: int
    summary: str
    why_risky: str
    suggested_question: str
    evidence_text: str
    page_number: int | None
    confidence_score: float


@dataclass(slots=True)
class RiskAnalysisResult:
    findings: list[RiskFindingDraft]
    missing_clauses: list[str]
    overall_risk_score: int
    overall_risk_level: str


class RiskEngine:
    """Deterministic rule engine for clause-level legal risk signals."""

    amount_re = re.compile(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)
    plain_amount_re = re.compile(r"\b([0-9][0-9,]{4,})\b")
    months_re = re.compile(r"\b(\d{1,3})\s*(?:month|months)\b", re.IGNORECASE)
    days_re = re.compile(r"\b(\d{1,3})\s*(?:day|days)\b", re.IGNORECASE)
    percent_re = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*%")

    def __init__(self, kb: LegalKnowledgeBase | None = None) -> None:
        self.kb = kb or get_legal_kb()
        self.normalizer = ClauseNormalizer(self.kb)
        self.universal_triggers = UniversalRiskTriggerEngine()
        self.evidence_validator = EvidenceValidator()
        self.post_processor = RiskPostProcessor()

    def analyze(
        self,
        contract_type: str,
        clauses: list[ClauseRiskInput],
        *,
        document_confidence: float = 0.85,
    ) -> RiskAnalysisResult:
        findings: list[RiskFindingDraft] = []

        for clause in clauses:
            findings.extend(self._evaluate_clause(contract_type=contract_type, clause=clause))
            findings.extend(
                self._evaluate_universal_triggers(
                    contract_type=contract_type,
                    clause=clause,
                    document_confidence=document_confidence,
                )
            )
            findings.extend(self._evaluate_kb_rules(contract_type=contract_type, clause=clause))

        missing_clauses = self._find_missing_clauses(contract_type=contract_type, clauses=clauses)
        for missing in missing_clauses:
            findings.append(
                self._missing_clause_finding(contract_type=contract_type, clause_type=missing)
            )
        for missing in self._find_recommended_review_clauses(
            contract_type=contract_type, clauses=clauses
        ):
            findings.append(
                self._recommended_clause_finding(contract_type=contract_type, clause_type=missing)
            )

        findings = self._validate_findings(findings, document_confidence=document_confidence)
        findings = self.post_processor.process(self._dedupe_findings(findings))

        overall_score = self._overall_score(findings)
        overall_level = self._risk_level(overall_score)

        sorted_findings = sorted(findings, key=lambda finding: finding.risk_score, reverse=True)
        return RiskAnalysisResult(
            findings=sorted_findings,
            missing_clauses=missing_clauses,
            overall_risk_score=overall_score,
            overall_risk_level=overall_level,
        )

    def _evaluate_clause(
        self, *, contract_type: str, clause: ClauseRiskInput
    ) -> list[RiskFindingDraft]:
        clause_type = clause.clause_type
        if clause_type == "compliance":
            finding = self._compliance_risk(contract_type=contract_type, clause=clause)
            return [finding] if finding else []
        if clause_type == "performance_obligations":
            finding = self._performance_risk(contract_type=contract_type, clause=clause)
            return [finding] if finding else []
        if clause_type == "service_level":
            finding = self._service_level_risk(clause)
            return [finding] if finding else []
        if clause_type == "data_privacy":
            finding = self._data_privacy_risk(contract_type=contract_type, clause=clause)
            return [finding] if finding else []
        if clause_type == "license":
            finding = self._license_risk(clause)
            return [finding] if finding else []
        if clause_type == "assignment":
            finding = self._assignment_risk(clause)
            return [finding] if finding else []
        if clause_type == "bond":
            finding = self._bond_risk(clause)
            return [finding] if finding else []
        if clause_type == "non_compete":
            finding = self._non_compete_risk(clause)
            return [finding] if finding else []
        if clause_type == "termination":
            finding = self._termination_risk(clause)
            return [finding] if finding else []
        if clause_type == "penalty":
            finding = self._penalty_risk(clause)
            return [finding] if finding else []
        if clause_type == "security_deposit":
            finding = self._security_deposit_risk(clause)
            return [finding] if finding else []
        if clause_type == "rent_escalation":
            finding = self._rent_escalation_risk(clause)
            return [finding] if finding else []
        if clause_type == "liability":
            finding = self._liability_risk(clause)
            return [finding] if finding else []
        if clause_type == "auto_renewal":
            finding = self._auto_renewal_risk(clause)
            return [finding] if finding else []
        if clause_type == "payment":
            finding = self._payment_risk(clause)
            return [finding] if finding else []
        if clause_type == "scope_of_services":
            finding = self._scope_risk(clause)
            return [finding] if finding else []
        if clause_type == "maintenance":
            finding = self._maintenance_risk(clause)
            return [finding] if finding else []
        return []

    def _evaluate_kb_rules(
        self, *, contract_type: str, clause: ClauseRiskInput
    ) -> list[RiskFindingDraft]:
        text = clause.normalized_text or clause.clause_text.lower()
        output: list[RiskFindingDraft] = []

        for rule in self.kb.risk_rules_for(contract_type, clause.clause_type):
            triggers = [str(item).lower() for item in rule.get("risk_triggers", [])]
            trigger_hits = [trigger for trigger in triggers if trigger in text]
            if not trigger_hits:
                continue

            mitigations = [str(item).lower() for item in rule.get("mitigating_terms", [])]
            mitigation_hits = [term for term in mitigations if term in text]
            severity = str(rule.get("base_severity", "medium"))
            score = RISK_LEVEL_SCORES.get(severity, RISK_LEVEL_SCORES["medium"])

            if severity in {"high", "critical"} and not mitigation_hits:
                score += 8
            if mitigation_hits:
                score -= min(16, 5 * len(mitigation_hits))
            if len(trigger_hits) >= 3:
                score += 6
            score = max(18, min(100, score))

            why = str(rule.get("why_risky", "The clause contains risk signals."))
            why = f"{why} Evidence signals: {', '.join(trigger_hits[:5])}." + (
                f" Mitigating language also found: {', '.join(mitigation_hits[:4])}."
                if mitigation_hits
                else ""
            )

            output.append(
                RiskFindingDraft(
                    clause_id=clause.id,
                    risk_category=f"{clause.clause_type}_playbook_risk",
                    risk_level=self._risk_level(score),
                    risk_score=score,
                    summary=str(rule.get("summary", "Potential clause risk detected.")),
                    why_risky=why,
                    suggested_question=str(
                        rule.get("suggested_question", "Can this clause be clarified or balanced?")
                    ),
                    evidence_text=clause.clause_text[:1000],
                    page_number=clause.page_start,
                    confidence_score=0.8 if not mitigation_hits else 0.68,
                )
            )

        return output

    def _evaluate_universal_triggers(
        self,
        *,
        contract_type: str,
        clause: ClauseRiskInput,
        document_confidence: float,
    ) -> list[RiskFindingDraft]:
        text = clause.normalized_text or clause.clause_text.lower()
        output: list[RiskFindingDraft] = []
        weight = self._document_weight(contract_type, clause.clause_type)
        for match in self.universal_triggers.detect(clause_type=clause.clause_type, text=text):
            score = self.universal_triggers.score(match, document_weight=weight)
            confidence = 0.76
            if match.mitigation_hits:
                confidence -= 0.12
            if document_confidence < 0.75:
                confidence -= 0.12
            why = (
                f"Universal risk trigger: {match.trigger_id}. "
                f"Evidence signals: {', '.join(match.signal_hits[:5])}."
            )
            if match.mitigation_hits:
                why += f" Mitigating language found: {', '.join(match.mitigation_hits[:4])}."
            output.append(
                RiskFindingDraft(
                    clause_id=clause.id,
                    risk_category=f"{match.trigger_id}_risk",
                    risk_level=self._risk_level(score),
                    risk_score=score,
                    summary=match.title,
                    why_risky=why,
                    suggested_question=match.suggested_question,
                    evidence_text=clause.clause_text[:1000],
                    page_number=clause.page_start,
                    confidence_score=max(0.35, min(0.92, confidence)),
                )
            )
        return output

    def _bond_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 20
        reasons: list[str] = []

        penalty_amount = self._max_amount(text)
        if penalty_amount is not None:
            score += 20
            reasons.append("fixed bond amount is specified")

        duration = self._max_months(text)
        if duration is not None and duration >= 12:
            score += 15
            reasons.append(f"minimum service period is long ({duration} months)")

        if "pro rata" not in text and "pro-rata" not in text and "prorata" not in text:
            score += 20
            reasons.append("no pro-rata reduction language found")

        if "training cost" in text and not any(
            keyword in text for keyword in ("breakdown", "itemized", "actual")
        ):
            score += 10
            reasons.append("training cost is referenced without clear cost breakdown")

        score = min(100, score)
        if score < 30:
            return None

        amount_label = (
            f"₹{int(penalty_amount):,}"
            if penalty_amount is not None and penalty_amount >= 1000
            else "a bond penalty"
        )
        summary = f"Bond clause may impose {amount_label} for early exit."
        why_risky = "Risk signals: " + ", ".join(reasons) + "."
        return self._build_finding(
            clause=clause,
            risk_category="financial_risk",
            risk_score=score,
            summary=summary,
            why_risky=why_risky,
            suggested_question=(
                "Is the bond amount pro-rated based on months already served, and can you share itemized training costs?"
            ),
        )

    def _non_compete_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 25
        reasons: list[str] = ["non-compete restrictions are present"]

        duration = self._max_months(text)
        if duration is not None and duration > 6:
            score += 20
            reasons.append(f"duration exceeds 6 months ({duration} months)")

        if not any(
            keyword in text
            for keyword in ("india", "state", "city", "territory", "geograph", "location")
        ):
            score += 10
            reasons.append("geographic scope is unclear")

        if any(
            phrase in text
            for phrase in (
                "any business",
                "in any capacity",
                "worldwide",
                "directly or indirectly",
                "any competitor",
            )
        ):
            score += 20
            reasons.append("restriction scope appears broad")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="employment_restriction_risk",
            risk_score=score,
            summary="Non-compete terms may restrict post-exit opportunities.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can the non-compete be narrowed by duration, geography, and role-specific scope?"
            ),
        )

    def _termination_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 15
        reasons: list[str] = []

        if any(
            phrase in text
            for phrase in ("without notice", "immediate termination", "terminate immediately")
        ):
            score += 30
            reasons.append("allows immediate or no-notice termination")

        employee_notice = self._extract_notice_for_party(text, party="employee")
        company_notice = self._extract_notice_for_party(text, party="employer")
        if employee_notice and company_notice and employee_notice > company_notice:
            score += 20
            reasons.append(
                f"employee notice burden ({employee_notice} days) exceeds employer notice ({company_notice} days)"
            )

        if "breach" in text and not any(
            keyword in text for keyword in ("cure period", "opportunity to cure", "remedy period")
        ):
            score += 15
            reasons.append("breach remediation window is missing")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="termination_risk",
            risk_score=score,
            summary="Termination terms may be unbalanced or abrupt.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can both parties have balanced notice requirements and a defined cure period before termination?"
            ),
        )

    def _penalty_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 20
        reasons: list[str] = []

        amount = self._max_amount(text)
        if amount is not None:
            score += 20
            reasons.append("explicit monetary penalty detected")

        if any(
            keyword in text
            for keyword in ("fixed", "non refundable", "non-refundable", "mandatory")
        ):
            score += 15
            reasons.append("penalty appears fixed or rigid")

        if not any(
            keyword in text
            for keyword in ("waive", "discretion", "mutual", "reasonable", "subject to")
        ):
            score += 10
            reasons.append("limited flexibility or exception language")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="financial_risk",
            risk_score=score,
            summary="Penalty clause may create high exit or breach cost.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can the penalty be reduced, made proportional, or conditioned on actual loss?"
            ),
        )

    def _security_deposit_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 12
        reasons: list[str] = []

        if "refund" not in text:
            score += 22
            reasons.append("refund terms are missing")
        if not any(keyword in text for keyword in ("days", "within", "timeline")):
            score += 18
            reasons.append("refund timeline is unclear")
        if "deduction" in text and not any(
            keyword in text for keyword in ("reasonable", "actual", "invoice")
        ):
            score += 10
            reasons.append("deduction criteria are broad")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="payment_risk",
            risk_score=score,
            summary="Security deposit terms may delay or reduce refund clarity.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can we define a fixed refund timeline and objective deduction rules with proof requirements?"
            ),
        )

    def _rent_escalation_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 10
        reasons: list[str] = []

        max_percent = self._max_percent(text)
        if max_percent is not None and max_percent > 10:
            score += 25
            reasons.append(f"rent escalation exceeds 10% ({max_percent:.1f}%)")
        elif max_percent is not None:
            score += 8
            reasons.append("rent escalation is present")

        if "annual" not in text and "year" not in text:
            score += 10
            reasons.append("escalation frequency is not explicit")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="financial_risk",
            risk_score=score,
            summary="Rent escalation may significantly increase recurring cost.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can the escalation percentage be capped and linked to a clear yearly schedule?"
            ),
        )

    def _liability_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 15
        reasons: list[str] = []

        if any(
            keyword in text
            for keyword in ("unlimited liability", "without limitation", "all losses")
        ):
            score += 25
            reasons.append("liability appears uncapped")

        if "indemn" in text and not any(keyword in text for keyword in ("mutual", "both parties")):
            score += 15
            reasons.append("indemnity appears one-sided")

        if not any(keyword in text for keyword in ("cap", "maximum", "limited to")):
            score += 10
            reasons.append("explicit liability cap is missing")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="liability_risk",
            risk_score=score,
            summary="Liability allocation may be broad or uncapped.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can we add a mutual and capped liability framework with clear exclusions?"
            ),
        )

    def _auto_renewal_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        signal = self.normalizer.signal_for("auto_renewal", text)
        if not signal.exists:
            return None
        score = 15
        reasons: list[str] = []

        if any(
            keyword in text
            for keyword in ("auto-renew", "automatically renew", "automatic renewal")
        ):
            score += 20
            reasons.append("contract renews automatically")

        if not any(keyword in text for keyword in ("notice", "cancel", "termination notice")):
            score += 20
            reasons.append("cancellation notice process is unclear")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="auto_renewal_risk",
            risk_score=score,
            summary="Auto-renewal language may lock parties into extended terms.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can we add an explicit reminder window and easy cancellation mechanism before renewal?"
            ),
        )

    def _payment_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 12
        reasons: list[str] = []

        if self._max_amount(text) is None and not any(
            marker in text for marker in ("rate", "rent", "fee", "charges", "retainer")
        ):
            score += 18
            reasons.append("amount or rate is not clearly stated")

        if not any(marker in text for marker in ("within", "due", "payable", "billing", "invoice")):
            score += 14
            reasons.append("payment due date or billing process is unclear")

        if any(
            marker in text for marker in ("sole discretion", "without notice", "unpaid in full")
        ):
            score += 12
            reasons.append("payment consequence language may be one-sided")

        score = min(100, score)
        if score < 28:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="payment_risk",
            risk_score=score,
            summary="Payment terms may need clearer amount, due-date, or consequence language.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can we make the amount, due date, late consequences, and billing process explicit?"
            ),
        )

    def _scope_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 14
        reasons: list[str] = []

        if any(
            marker in text
            for marker in ("not covered", "separate written agreement", "additional services")
        ):
            score += 12
            reasons.append("some services require a separate agreement")
        if not any(marker in text for marker in ("include", "covered", "scope", "services")):
            score += 16
            reasons.append("included services are not clearly enumerated")

        score = min(100, score)
        if score < 28:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="scope_risk",
            risk_score=score,
            summary="Scope of services may leave room for disputes about what is included.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question="Can we list exactly which services are included and excluded?",
        )

    def _maintenance_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 12
        reasons: list[str] = []

        if not any(marker in text for marker in ("owner", "landlord")):
            score += 10
            reasons.append("owner responsibility is not explicit")
        if not any(marker in text for marker in ("tenant", "lessee")):
            score += 10
            reasons.append("tenant responsibility is not explicit")
        if any(marker in text for marker in ("all charges", "any claims", "harmless")):
            score += 10
            reasons.append("responsibility may be broad")

        score = min(100, score)
        if score < 28:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="maintenance_risk",
            risk_score=score,
            summary="Maintenance or utility responsibility may need clearer allocation.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question="Can we clearly split owner and tenant duties for repairs, utilities, and charges?",
        )

    def _compliance_risk(
        self, *, contract_type: str, clause: ClauseRiskInput
    ) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 12
        reasons: list[str] = []

        if any(marker in text for marker in ("blacklist", "blacklisting", "debar", "debarment")):
            score += 34
            reasons.append("blacklisting or debarment consequences are mentioned")
        if any(
            marker in text
            for marker in ("sole discretion", "without assigning any reason", "without reason")
        ):
            score += 18
            reasons.append("authority discretion appears broad")
        if any(
            marker in text
            for marker in ("all applicable laws", "all regulations", "from time to time")
        ):
            score += 10
            reasons.append("compliance duty is broad and may change over time")
        if contract_type == "government_empanelment":
            score += 8
            reasons.append("government/empanelment terms can affect eligibility for future work")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="compliance_risk",
            risk_score=score,
            summary="Compliance terms may create eligibility or debarment exposure.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can the compliance breach process define notice, cure period, evidence, and appeal rights?"
            ),
        )

    def _performance_risk(
        self, *, contract_type: str, clause: ClauseRiskInput
    ) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 12
        reasons: list[str] = []

        if any(
            marker in text
            for marker in ("no guaranteed work", "no assurance of work", "no work guarantee")
        ):
            score += 24
            reasons.append("empanelment may not guarantee any paid work")
        if any(
            marker in text
            for marker in ("sole satisfaction", "sole discretion", "approval of the authority")
        ):
            score += 18
            reasons.append("acceptance or review depends heavily on one party")
        if any(
            marker in text for marker in ("work order", "purchase order", "as and when required")
        ):
            score += 8
            reasons.append("obligations may depend on future work orders")
        if "milestone" in text and not any(
            marker in text for marker in ("acceptance criteria", "deemed accepted", "timeline")
        ):
            score += 12
            reasons.append("milestones are mentioned without objective acceptance criteria")
        if contract_type == "government_empanelment":
            score += 6

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="performance_risk",
            risk_score=score,
            summary="Performance or approval terms may leave payment or work allocation uncertain.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can work allocation, acceptance criteria, rejection reasons, and payment triggers be made explicit?"
            ),
        )

    def _service_level_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 12
        reasons: list[str] = []

        if (
            "uptime" in text
            and self._max_percent(text) is not None
            and self._max_percent(text) < 99
        ):
            score += 16
            reasons.append("uptime commitment may be low")
        if any(
            marker in text for marker in ("best effort", "best efforts", "as is", "no warranty")
        ):
            score += 22
            reasons.append("service commitment may be best-efforts or warranty-limited")
        if not any(
            marker in text
            for marker in ("response time", "resolution time", "service credit", "support hours")
        ):
            score += 14
            reasons.append("support response, resolution, or service credits are unclear")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="service_level_risk",
            risk_score=score,
            summary="Service levels may not give enough operational protection.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can we add measurable uptime, response time, resolution time, and service-credit remedies?"
            ),
        )

    def _data_privacy_risk(
        self, *, contract_type: str, clause: ClauseRiskInput
    ) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 12
        reasons: list[str] = []

        if any(marker in text for marker in ("personal data", "sensitive data", "customer data")):
            score += 12
            reasons.append("personal or customer data is involved")
        if not any(marker in text for marker in ("delete", "deletion", "return", "destroy")):
            score += 16
            reasons.append("data return/deletion after termination is unclear")
        if "subprocessor" in text and not any(
            marker in text for marker in ("notice", "approval", "objection")
        ):
            score += 12
            reasons.append("subprocessor approval or notice rights are unclear")
        if contract_type == "software_saas_agreement" and not any(
            marker in text for marker in ("security measures", "breach notification", "incident")
        ):
            score += 12
            reasons.append("security and breach-notification obligations are not specific")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="data_privacy_risk",
            risk_score=score,
            summary="Data handling terms may be incomplete for operational or privacy risk.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question=(
                "Can data security, breach notice, subprocessors, and deletion/return obligations be clarified?"
            ),
        )

    def _license_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 12
        reasons: list[str] = []

        if any(marker in text for marker in ("revocable", "non-transferable", "non-sublicensable")):
            score += 8
            reasons.append("license is tightly restricted")
        if not any(
            marker in text
            for marker in ("term", "duration", "subscription period", "permitted use")
        ):
            score += 16
            reasons.append("license term or permitted use is unclear")
        if any(marker in text for marker in ("audit", "suspend", "disable access")):
            score += 12
            reasons.append("provider may audit, suspend, or disable access")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="license_risk",
            risk_score=score,
            summary="License terms may restrict use or access more than expected.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question="Can permitted users, use cases, term, suspension rights, and post-termination access be clarified?",
        )

    def _assignment_risk(self, clause: ClauseRiskInput) -> RiskFindingDraft | None:
        text = clause.normalized_text
        score = 12
        reasons: list[str] = []

        if any(
            marker in text for marker in ("without consent", "without prior consent", "at any time")
        ):
            score += 18
            reasons.append("assignment may be allowed without consent")
        if "subcontract" in text and not any(
            marker in text for marker in ("responsible", "liable", "approval")
        ):
            score += 14
            reasons.append("subcontracting responsibility or approval is unclear")

        score = min(100, score)
        if score < 30:
            return None

        return self._build_finding(
            clause=clause,
            risk_category="assignment_risk",
            risk_score=score,
            summary="Assignment or subcontracting terms may reduce control over who performs the agreement.",
            why_risky="Risk signals: " + ", ".join(reasons) + ".",
            suggested_question="Can assignment and subcontracting require consent and keep the original party responsible?",
        )

    def _find_missing_clauses(
        self, contract_type: str, clauses: list[ClauseRiskInput]
    ) -> list[str]:
        expected = tuple(
            self.kb.expected_clauses(contract_type)
        ) or EXPECTED_CLAUSES_BY_CONTRACT.get(contract_type, ())
        if not expected:
            return []

        present = self._present_clause_types(clauses)
        return [clause_type for clause_type in expected if clause_type not in present]

    def _find_recommended_review_clauses(
        self,
        contract_type: str,
        clauses: list[ClauseRiskInput],
    ) -> list[str]:
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

    def _missing_clause_finding(self, *, contract_type: str, clause_type: str) -> RiskFindingDraft:
        kb_profile = self.kb.missing_clause_profile(contract_type, clause_type)
        profile = DOCUMENT_ANALYSIS_PROFILES.get(contract_type, {})
        risk_map = profile.get("missing_clause_risk", {})
        severity = "low"
        if kb_profile.get("missing_severity"):
            severity = str(kb_profile["missing_severity"])
        elif isinstance(risk_map, dict):
            severity = str(risk_map.get(clause_type, "low"))
        score = RISK_LEVEL_SCORES.get(severity, RISK_LEVEL_SCORES["low"])
        label = clause_type.replace("_", " ")
        expected_for = self.kb.playbook(contract_type).get("purpose") or profile.get(
            "purpose", "this document type"
        )
        why_expected = kb_profile.get("why_expected")
        expectation_level = self._missing_expectation_level(severity)
        why = (
            f"For {expected_for}, a {label} clause is {expectation_level}. Its absence can create "
            "ambiguity about rights, obligations, or remedies."
        )
        if why_expected:
            why = f"{why_expected} Missing or unclear wording may create ambiguity about rights, obligations, or remedies."
        if severity in {"low", "informational"}:
            why = (
                f"A {label} clause can be useful for this document type, but the absence is not automatically "
                "a major legal risk unless the surrounding terms create practical harm."
            )

        return RiskFindingDraft(
            clause_id=None,
            risk_category="missing_protection_risk",
            risk_level=self._risk_level(score),
            risk_score=score,
            summary=f"{expectation_level.title()} clause not clearly found: {label}.",
            why_risky=why,
            suggested_question=f"Should this document include or clarify {label} for this exact agreement type?",
            evidence_text="Not found after checking extracted clause labels and equivalent keyword evidence.",
            page_number=None,
            confidence_score=0.6 if severity in {"low", "informational"} else 0.72,
        )

    def _recommended_clause_finding(
        self, *, contract_type: str, clause_type: str
    ) -> RiskFindingDraft:
        profile = self.kb.playbook(contract_type) or DOCUMENT_ANALYSIS_PROFILES.get(
            contract_type, {}
        )
        label = clause_type.replace("_", " ")
        purpose = profile.get("purpose", "this agreement")
        score = RISK_LEVEL_SCORES["informational"]
        return RiskFindingDraft(
            clause_id=None,
            risk_category="recommended_review_gap",
            risk_level=self._risk_level(score),
            risk_score=score,
            summary=f"Optional review point not clearly found: {label}.",
            why_risky=(
                f"This is not treated as a core missing clause for {purpose}, but reviewing it can reduce "
                "implementation disputes or hidden commercial exposure."
            ),
            suggested_question=f"Would adding {label} materially reduce uncertainty for this deal?",
            evidence_text="Not found in extracted contract sections; treated as optional review, not a major risk by itself.",
            page_number=None,
            confidence_score=0.55,
        )

    def _present_clause_types(self, clauses: list[ClauseRiskInput]) -> set[str]:
        present = {clause.clause_type for clause in clauses}
        clause_texts = [
            (clause.clause_title, clause.normalized_text or clause.clause_text.lower())
            for clause in clauses
        ]
        normalized_present = self.normalizer.present_clause_types(clause_texts)
        present.update(normalized_present)
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
            # A strong phrase like "security deposit" is enough; generic single words need multiple signals.
            if any(" " in keyword for keyword in matched) or len(matched) >= 2:
                present.add(clause_type)

        return present

    def _validate_findings(
        self,
        findings: list[RiskFindingDraft],
        *,
        document_confidence: float,
    ) -> list[RiskFindingDraft]:
        output: list[RiskFindingDraft] = []
        for finding in findings:
            validation = self.evidence_validator.validate(finding)
            if validation.action == "drop":
                continue
            confidence = finding.confidence_score + validation.confidence_delta
            if document_confidence < 0.75:
                confidence -= 0.12
            if finding.evidence_text and len(" ".join(finding.evidence_text.split())) < 50:
                confidence -= 0.05
            score = max(0, min(100, finding.risk_score + validation.score_delta))
            output.append(
                RiskFindingDraft(
                    clause_id=finding.clause_id,
                    risk_category=finding.risk_category,
                    risk_level=self._risk_level(score),
                    risk_score=score,
                    summary=finding.summary,
                    why_risky=finding.why_risky,
                    suggested_question=finding.suggested_question,
                    evidence_text=finding.evidence_text,
                    page_number=finding.page_number,
                    confidence_score=max(0.15, min(0.95, confidence)),
                )
            )
        return output

    @staticmethod
    def _document_weight(contract_type: str, clause_type: str) -> float:
        if contract_type == "legal_template_collection":
            return 0.85
        if contract_type == "loan_agreement" and clause_type in {
            "payment",
            "penalty",
            "termination",
        }:
            return 1.12
        if contract_type == "software_saas_agreement" and clause_type in {
            "data_privacy",
            "license",
            "service_level",
            "liability",
        }:
            return 1.12
        if contract_type == "government_empanelment" and clause_type in {
            "compliance",
            "performance_obligations",
            "termination",
        }:
            return 1.12
        if contract_type == "rental_agreement" and clause_type in {
            "security_deposit",
            "maintenance",
            "payment",
        }:
            return 1.08
        return 1.0

    @staticmethod
    def _missing_expectation_level(severity: str) -> str:
        if severity in {"critical", "high"}:
            return "required"
        if severity == "medium":
            return "expected"
        if severity in {"low", "informational"}:
            return "optional"
        return "expected"

    @staticmethod
    def _dedupe_findings(findings: list[RiskFindingDraft]) -> list[RiskFindingDraft]:
        output: list[RiskFindingDraft] = []
        seen: set[tuple[str, str, int | None]] = set()
        for finding in findings:
            key = (
                finding.risk_category,
                " ".join(finding.summary.lower().split()),
                finding.clause_id,
            )
            if key in seen:
                continue
            seen.add(key)
            output.append(finding)
        return output

    def _overall_score(self, findings: list[RiskFindingDraft]) -> int:
        material_findings = [
            finding for finding in findings if finding.risk_category != "recommended_review_gap"
        ]
        if not material_findings:
            return 18

        top_scores = [
            finding.risk_score
            for finding in sorted(
                material_findings, key=lambda item: item.risk_score, reverse=True
            )[:8]
        ]
        mean_top = sum(top_scores) / len(top_scores)
        amplification = min(12.0, len(material_findings) * 1.4)
        score = int(round(min(100.0, mean_top + amplification)))
        return max(0, score)

    def _build_finding(
        self,
        *,
        clause: ClauseRiskInput,
        risk_category: str,
        risk_score: int,
        summary: str,
        why_risky: str,
        suggested_question: str,
    ) -> RiskFindingDraft:
        score = max(0, min(100, risk_score))
        return RiskFindingDraft(
            clause_id=clause.id,
            risk_category=risk_category,
            risk_level=self._risk_level(score),
            risk_score=score,
            summary=summary,
            why_risky=why_risky,
            suggested_question=suggested_question,
            evidence_text=clause.clause_text[:1000],
            page_number=clause.page_start,
            confidence_score=self._confidence_from_score(score),
        )

    def _extract_notice_for_party(self, text: str, party: str) -> int | None:
        if party == "employee":
            patterns = (
                r"employee[^.]{0,120}?(\d{1,3})\s*day",
                r"you[^.]{0,120}?(\d{1,3})\s*day",
                r"resign[^.]{0,120}?(\d{1,3})\s*day",
            )
        else:
            patterns = (
                r"employer[^.]{0,120}?(\d{1,3})\s*day",
                r"company[^.]{0,120}?(\d{1,3})\s*day",
            )

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
        return None

    def _max_amount(self, text: str) -> float | None:
        amounts: list[float] = []

        for match in self.amount_re.finditer(text):
            value = match.group(1).replace(",", "")
            try:
                amounts.append(float(value))
            except ValueError:
                continue

        if not amounts:
            for match in self.plain_amount_re.finditer(text):
                value = match.group(1).replace(",", "")
                try:
                    parsed = float(value)
                except ValueError:
                    continue
                if parsed >= 1000:
                    amounts.append(parsed)

        return max(amounts) if amounts else None

    def _max_months(self, text: str) -> int | None:
        months = [int(match.group(1)) for match in self.months_re.finditer(text)]
        return max(months) if months else None

    def _max_percent(self, text: str) -> float | None:
        percentages = [float(match.group(1)) for match in self.percent_re.finditer(text)]
        return max(percentages) if percentages else None

    @staticmethod
    def _phrase_in_text(text: str, phrase: str) -> bool:
        return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text))

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
    def _confidence_from_score(score: int) -> float:
        if score >= 76:
            return 0.9
        if score >= 51:
            return 0.82
        if score >= 26:
            return 0.72
        return 0.6
