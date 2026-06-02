from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class UniversalRiskTrigger:
    trigger_id: str
    title: str
    signals: tuple[str, ...]
    mitigations: tuple[str, ...] = ()
    base_level: str = "medium"
    clause_types: tuple[str, ...] = ()
    suggested_question: str = "Can this term be clarified, narrowed, or made mutual?"


@dataclass(slots=True)
class UniversalRiskMatch:
    trigger_id: str
    title: str
    base_level: str
    signal_hits: list[str] = field(default_factory=list)
    mitigation_hits: list[str] = field(default_factory=list)
    suggested_question: str = ""


class UniversalRiskTriggerEngine:
    """Generic risk trigger detection independent of document type."""

    triggers: tuple[UniversalRiskTrigger, ...] = (
        UniversalRiskTrigger(
            trigger_id="unilateral_discretion",
            title="Unilateral discretion may be broad",
            signals=(
                "at sole discretion",
                "sole and final",
                "without assigning any reason",
                "as it deems fit",
                "from time to time",
                "without liability",
            ),
            mitigations=("reasonable", "written reasons", "notice", "cure period", "appeal"),
            base_level="medium",
            suggested_question="Can discretion be tied to objective reasons, notice, and review/cure rights?",
        ),
        UniversalRiskTrigger(
            trigger_id="uncapped_liability",
            title="Liability may be uncapped or very broad",
            signals=(
                "all losses",
                "whatsoever",
                "without limitation",
                "indemnify and hold harmless",
                "any and all claims",
                "unlimited liability",
            ),
            mitigations=("cap", "maximum", "limited to", "aggregate liability", "fees paid"),
            base_level="high",
            suggested_question="Can liability be capped, mutual, and limited to direct losses with clear exclusions?",
        ),
        UniversalRiskTrigger(
            trigger_id="immediate_acceleration",
            title="Immediate repayment or acceleration may be harsh",
            signals=(
                "entire outstanding shall become payable forthwith",
                "immediately repay",
                "recall the loan",
                "all amounts become due",
                "due and payable immediately",
            ),
            mitigations=("notice", "cure", "grace period", "material breach"),
            base_level="high",
            suggested_question="Can acceleration require material default, notice, and a cure/grace period?",
        ),
        UniversalRiskTrigger(
            trigger_id="ambiguous_commercial_terms",
            title="Commercial terms may be blank, variable, or approval-dependent",
            signals=(
                "as may be decided",
                "from time to time",
                "subject to approval",
                "subject to acceptance",
                "as determined by",
            ),
            mitigations=("schedule", "annexure", "within", "deemed accepted", "objective criteria"),
            base_level="medium",
            suggested_question="Can amount, timing, approval criteria, and consequences be made objective?",
        ),
        UniversalRiskTrigger(
            trigger_id="non_neutral_dispute_resolution",
            title="Dispute decision-maker may not be neutral",
            signals=(
                "decision of the company shall be final",
                "decision of the bank shall be final",
                "decision of the authority shall be final",
                "sole arbitrator appointed by",
                "final and binding decision",
            ),
            mitigations=("mutually appointed", "independent", "court", "institutional arbitration"),
            base_level="medium",
            suggested_question="Can dispute resolution use a neutral forum or mutually appointed decision-maker?",
        ),
        UniversalRiskTrigger(
            trigger_id="forfeiture",
            title="Forfeiture language may cause loss of money or rights",
            signals=("forfeit", "forfeiture", "non-refundable", "no refund", "no compensation"),
            mitigations=("actual loss", "reasonable", "pro rata", "completed work", "itemized"),
            base_level="medium",
            suggested_question="Can forfeiture be limited to actual loss and preserve completed-work payment?",
        ),
    )

    severity_scores = {
        "critical": 82,
        "high": 62,
        "medium_high": 52,
        "medium": 38,
        "low": 18,
    }

    def detect(self, *, clause_type: str, text: str) -> list[UniversalRiskMatch]:
        lowered = " ".join(text.lower().split())
        matches: list[UniversalRiskMatch] = []
        for trigger in self.triggers:
            if trigger.clause_types and clause_type not in trigger.clause_types:
                continue
            signal_hits = [signal for signal in trigger.signals if signal in lowered]
            if not signal_hits:
                continue
            mitigation_hits = [
                mitigation for mitigation in trigger.mitigations if mitigation in lowered
            ]
            matches.append(
                UniversalRiskMatch(
                    trigger_id=trigger.trigger_id,
                    title=trigger.title,
                    base_level=trigger.base_level,
                    signal_hits=signal_hits,
                    mitigation_hits=mitigation_hits,
                    suggested_question=trigger.suggested_question,
                )
            )
        return matches

    def score(self, match: UniversalRiskMatch, *, document_weight: float = 1.0) -> int:
        score = self.severity_scores.get(match.base_level, 38)
        score += min(10, 3 * (len(match.signal_hits) - 1))
        score -= min(16, 5 * len(match.mitigation_hits))
        return max(12, min(100, int(round(score * document_weight))))
