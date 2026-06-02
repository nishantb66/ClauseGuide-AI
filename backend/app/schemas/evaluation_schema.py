from datetime import datetime

from pydantic import BaseModel, Field


class EvaluationTestCase(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    expected_answer: str | None = None
    expected_source_page: int | None = None
    expected_clause_type: str | None = None
    expected_risk_level: str | None = None


class EvaluationRunRequest(BaseModel):
    run_label: str = Field(default="default", min_length=1, max_length=120)
    use_ragas: bool = False
    test_cases: list[EvaluationTestCase] | None = None


class EvaluationResultItem(BaseModel):
    question: str
    expected_answer: str | None = None
    actual_answer: str

    faithfulness_score: float | None = None
    answer_relevancy_score: float | None = None
    context_precision_score: float | None = None
    context_recall_score: float | None = None

    amount_accuracy_score: float
    date_accuracy_score: float
    clause_classification_score: float
    risk_level_accuracy_score: float
    citation_exact_match_score: float
    unsupported_refusal_score: float


class EvaluationMetricsSummary(BaseModel):
    total_cases: int
    ragas_enabled: bool
    ragas_applied: bool

    faithfulness_score: float | None = None
    answer_relevancy_score: float | None = None
    context_precision_score: float | None = None
    context_recall_score: float | None = None

    amount_accuracy_score: float
    date_accuracy_score: float
    clause_classification_score: float
    risk_level_accuracy_score: float
    citation_exact_match_score: float
    unsupported_refusal_score: float


class EvaluationRunResponse(BaseModel):
    run_id: str
    document_id: str
    run_label: str
    created_at: datetime
    metrics: EvaluationMetricsSummary
    results: list[EvaluationResultItem]


class EvaluationRunListItem(BaseModel):
    run_id: str
    run_label: str
    created_at: datetime
    metrics: EvaluationMetricsSummary


class EvaluationRunListResponse(BaseModel):
    document_id: str
    runs: list[EvaluationRunListItem]
