from app.services.reranker import ChunkReranker
from app.services.retriever import RetrievalItem


def test_heuristic_reranker_prioritizes_clause_match() -> None:
    reranker = ChunkReranker()

    items = [
        RetrievalItem(
            chunk_id=1,
            page_number=1,
            chunk_text="This section describes confidentiality obligations and disclosure restrictions.",
            clause_type="confidentiality",
            section_title="Confidentiality",
            semantic_score=0.5,
            keyword_score=0.4,
            merged_score=0.46,
            score=0.46,
        ),
        RetrievalItem(
            chunk_id=2,
            page_number=2,
            chunk_text="The employee shall pay a bond amount if they leave before 18 months.",
            clause_type="bond",
            section_title="Service Bond",
            semantic_score=0.48,
            keyword_score=0.45,
            merged_score=0.465,
            score=0.465,
        ),
    ]

    ranked, diagnostics = reranker.rerank(
        query="Can I leave before bond period ends?",
        items=items,
        required_clause_types=["bond", "termination", "penalty"],
        top_k=2,
    )

    assert diagnostics.model_used in {"heuristic", "cross_encoder"}
    assert ranked[0].chunk_id == 2
    assert ranked[0].score >= ranked[1].score
