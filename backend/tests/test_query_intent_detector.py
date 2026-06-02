from app.services.query_intent_detector import QueryIntentDetector


def test_detects_termination_intent_and_clause_focus() -> None:
    detector = QueryIntentDetector()

    result = detector.detect("Can I leave before the bond period ends and what penalty applies?")

    assert result.intent == "termination_question"
    assert "bond" in result.required_clause_types
    assert "termination" in result.required_clause_types
    assert len(result.rewritten_query) >= len("Can I leave before the bond period ends and what penalty applies?")


def test_detects_missing_clause_question() -> None:
    detector = QueryIntentDetector()

    result = detector.detect("Which important clauses are missing from this agreement?")

    assert result.intent == "missing_clause_question"
    assert result.confidence_score >= 0.25


def test_termination_query_without_penalty_stays_focused() -> None:
    detector = QueryIntentDetector()

    result = detector.detect("What is the termination notice period?")

    assert result.intent == "termination_question"
    assert "termination" in result.required_clause_types
    assert "notice_period" in result.required_clause_types
    assert "penalty" not in result.required_clause_types


def test_document_overview_intent_for_broad_summary() -> None:
    detector = QueryIntentDetector()

    result = detector.detect("Tell me about this document")

    assert result.intent == "document_overview"
    assert result.required_clause_types == []
