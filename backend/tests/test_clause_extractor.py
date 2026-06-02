from app.services.chunker import ChunkRecord
from app.services.clause_extractor import ClauseExtractor


def test_clause_extractor_classifies_clauses() -> None:
    extractor = ClauseExtractor()
    chunks = [
        ChunkRecord(
            page_number=1,
            chunk_index=0,
            chunk_text=(
                "SERVICE BOND The employee shall pay Rs 150000 if they leave early. "
                "No pro-rata reduction is described."
            ),
            token_count=24,
            section_title="Clause 4: Service Bond",
            clause_type="bond",
            start_char=0,
            end_char=120,
        ),
        ChunkRecord(
            page_number=2,
            chunk_index=1,
            chunk_text=(
                "TERMINATION The employer may terminate immediately without notice. "
                "The employee must provide 60 days notice."
            ),
            token_count=23,
            section_title="Clause 8: Termination",
            clause_type="termination",
            start_char=121,
            end_char=245,
        ),
    ]

    clauses = extractor.extract(chunks)

    clause_types = {clause.clause_type for clause in clauses}
    assert "bond" in clause_types
    assert "termination" in clause_types
    assert all(clause.confidence_score >= 0.35 for clause in clauses)


def test_clause_extractor_avoids_false_penalty_from_compensation_language() -> None:
    extractor = ClauseExtractor()
    chunks = [
        ChunkRecord(
            page_number=2,
            chunk_index=0,
            chunk_text=(
                "Compensation Committee review and evaluation of incentive and retirement plans "
                "shall occur annually."
            ),
            token_count=18,
            section_title="Compensation Review",
            clause_type="payment",
            start_char=0,
            end_char=110,
        )
    ]

    clauses = extractor.extract(chunks)
    assert not any(clause.clause_type in {"penalty", "bond"} for clause in clauses)
