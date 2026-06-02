from app.schemas.evaluation_schema import EvaluationTestCase
from app.services.evaluation_service import EvaluationService


def test_score_case_detects_amount_and_citation() -> None:
    service = EvaluationService()
    case = EvaluationTestCase(
        question="What penalty amount applies?",
        expected_answer="The penalty is INR 150000 if you resign early.",
        expected_source_page=3,
        expected_clause_type="bond",
        expected_risk_level="high",
    )
    answer = {
        "answer": "The contract says you may need to pay INR 150000 for early exit.",
        "sources": [{"page": 3, "clause_type": "bond", "evidence": "pay INR 150000"}],
        "retrieved_context": [
            "Clause 4: Employee shall pay INR 150000 if leaving before 18 months.",
        ],
    }

    row = service._score_case(case=case, answer=answer, risk_level_by_clause={"bond": "high"})

    assert row.amount_accuracy_score == 1.0
    assert row.citation_exact_match_score == 1.0
    assert row.clause_classification_score == 1.0
    assert row.risk_level_accuracy_score == 1.0


def test_score_case_unsupported_refusal() -> None:
    service = EvaluationService()
    case = EvaluationTestCase(
        question="Is there a clause about free lunch?",
        expected_answer=None,
    )
    answer = {
        "answer": "I could not find this information in the contract.",
        "sources": [],
        "retrieved_context": [],
    }

    row = service._score_case(case=case, answer=answer, risk_level_by_clause={})

    assert row.unsupported_refusal_score == 1.0
    assert row.context_precision_score == 0.0


def test_extract_ragas_summary_from_dict() -> None:
    service = EvaluationService()

    result = service._extract_ragas_summary(
        {
            "faithfulness": 0.9,
            "answer_relevancy": 0.8,
            "context_precision": 0.7,
            "context_recall": 0.6,
        }
    )

    assert result["faithfulness_score"] == 0.9
    assert result["answer_relevancy_score"] == 0.8
    assert result["context_precision_score"] == 0.7
    assert result["context_recall_score"] == 0.6
