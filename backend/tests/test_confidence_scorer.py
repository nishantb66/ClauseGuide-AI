from app.services.confidence_scorer import ConfidenceScorer, ConfidenceSignals


def test_confidence_scorer_high_label() -> None:
    scorer = ConfidenceScorer()
    result = scorer.score(
        ConfidenceSignals(
            retrieval_score=0.92,
            reranker_score=0.88,
            citation_score=1.0,
            clause_coverage_score=0.9,
            intent_support_score=0.84,
        )
    )

    assert result.score >= 0.8
    assert result.label == "high"


def test_confidence_scorer_not_enough_evidence() -> None:
    scorer = ConfidenceScorer()
    result = scorer.score(
        ConfidenceSignals(
            retrieval_score=0.1,
            reranker_score=0.12,
            citation_score=0.0,
            clause_coverage_score=0.15,
            intent_support_score=0.2,
        )
    )

    assert result.score < 0.4
    assert result.label == "not_enough_evidence"
