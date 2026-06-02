from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ConfidenceSignals:
    retrieval_score: float
    reranker_score: float
    citation_score: float
    clause_coverage_score: float
    intent_support_score: float


@dataclass(slots=True)
class ConfidenceResult:
    score: float
    label: str


class ConfidenceScorer:
    """Combines retrieval and verification signals into conservative confidence estimates."""

    def score(self, signals: ConfidenceSignals) -> ConfidenceResult:
        weighted = (
            0.30 * self._clip(signals.retrieval_score)
            + 0.25 * self._clip(signals.reranker_score)
            + 0.20 * self._clip(signals.citation_score)
            + 0.15 * self._clip(signals.clause_coverage_score)
            + 0.10 * self._clip(signals.intent_support_score)
        )

        score = round(self._clip(weighted), 4)
        if score >= 0.80:
            label = "high"
        elif score >= 0.60:
            label = "medium"
        elif score >= 0.40:
            label = "low"
        else:
            label = "not_enough_evidence"

        return ConfidenceResult(score=score, label=label)

    @staticmethod
    def _clip(value: float) -> float:
        return max(0.0, min(1.0, value))
