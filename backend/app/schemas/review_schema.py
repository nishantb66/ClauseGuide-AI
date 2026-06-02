from pydantic import BaseModel, Field

from app.schemas.verification_schema import VerificationResult


class HighlightRect(BaseModel):
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    page_width: float
    page_height: float


class TextHighlight(BaseModel):
    page: int
    statement: str
    start_char: int | None = None
    end_char: int | None = None
    match_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    rects: list[HighlightRect] = Field(default_factory=list)


class ReviewRiskItem(BaseModel):
    finding_id: int
    clause_id: int | None = None
    clause_type: str
    risk_category: str
    risk_level: str
    risk_score: int = Field(ge=0, le=100)
    title: str
    summary: str
    why_risky: str
    suggested_question: str
    page: int
    evidence: str
    highlight: TextHighlight | None = None
    verification: VerificationResult | None = None


class ReviewPageItem(BaseModel):
    page: int
    text: str


class ReviewWorkspaceResponse(BaseModel):
    document_id: str
    title: str
    file_name: str
    file_type: str
    total_pages: int
    file_url: str
    canvas_mode: str
    risks: list[ReviewRiskItem]
    pages: list[ReviewPageItem]


class ImportantPointItem(BaseModel):
    id: str
    title: str
    reason: str
    action: str
    risk_level: str
    risk_score: int
    page: int
    source_finding_id: int | None = None
    highlight: TextHighlight | None = None
    verification: VerificationResult | None = None


class ImportantPointsResponse(BaseModel):
    document_id: str
    title: str
    file_name: str
    file_type: str
    total_pages: int
    file_url: str
    canvas_mode: str
    points: list[ImportantPointItem]
    pages: list[ReviewPageItem]
