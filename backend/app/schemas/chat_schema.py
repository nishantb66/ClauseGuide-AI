from pydantic import BaseModel, Field

from app.schemas.verification_schema import VerificationResult


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    session_id: str | None = None


class ChatSource(BaseModel):
    page: int
    clause_type: str
    evidence: str


class ChatResponse(BaseModel):
    answer: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_label: str
    sources: list[ChatSource]
    disclaimer: str
    intent: str
    required_clause_types: list[str]
    session_id: str
    verification: VerificationResult | None = None
