from app.services.citation_verifier import CitationVerifier


def test_citation_verifier_pass() -> None:
    verifier = CitationVerifier()
    sources = [{"page": 1, "evidence": "notice period is 30 days", "clause_type": "notice_period"}]
    context = ["The notice period is 30 days for resignation."]

    assert verifier.verify(sources=sources, retrieved_context=context)


def test_citation_verifier_fail() -> None:
    verifier = CitationVerifier()
    sources = [{"page": 1, "evidence": "never appears", "clause_type": "other"}]
    context = ["Completely unrelated sentence."]

    assert not verifier.verify(sources=sources, retrieved_context=context)


def test_citation_verifier_fuzzy_overlap_score() -> None:
    verifier = CitationVerifier()
    sources = [{"page": 3, "evidence": "employee must provide 30 days written notice before resignation"}]
    context = ["The employee shall provide thirty days written notice before resignation from services."]

    assert verifier.score(sources=sources, retrieved_context=context) > 0.7
