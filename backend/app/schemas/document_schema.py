from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.verification_schema import VerificationResult, VerificationSummary


class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str


class ProcessResponse(BaseModel):
    document_id: str
    status: str
    contract_type: str
    total_pages: int = 0
    total_chunks: int = 0
    clauses_extracted: int = 0
    risk_findings: int = 0


class DocumentSummary(BaseModel):
    id: str
    title: str
    file_name: str
    file_type: str
    contract_type: str | None
    status: str
    total_pages: int
    uploaded_at: datetime
    processed_at: datetime | None


class AnalysisRiskItem(BaseModel):
    finding_id: int | None = None
    clause_type: str
    clause_id: int | None = None
    risk_level: str
    risk_score: int = Field(ge=0, le=100)
    risk_category: str
    summary: str
    why_risky: str
    suggested_question: str
    page: int
    evidence: str | None = None
    plain_language: str | None = None
    verification: VerificationResult | None = None


class ExtractionHealth(BaseModel):
    clauses_found: int
    risks_found: int
    source_pages: list[int] = Field(default_factory=list)
    note: str


class DocumentProfile(BaseModel):
    purpose: str
    likely_user_role: str
    stronger_party: str
    detected_parties: list[str] = Field(default_factory=list)
    party_roles: list[dict] = Field(default_factory=list)
    governing_law: str | None = None


class DocumentSectionClassificationItem(BaseModel):
    document_type: str
    title: str
    page_start: int
    page_end: int
    confidence_score: float


class DocumentClassificationInfo(BaseModel):
    primary_document_type: str
    secondary_document_types: list[str] = Field(default_factory=list)
    is_template: bool = False
    is_executed_agreement: bool = False
    is_collection_or_handbook: bool = False
    contains_multiple_document_types: bool = False
    confidence_score: float = 0.0
    sections: list[DocumentSectionClassificationItem] = Field(default_factory=list)


class CuadCoverage(BaseModel):
    enabled: bool = False
    source: str = "theatticusproject/cuad"
    license: str = "CC BY 4.0"
    contract_count: int = 0
    cuad_label_count: int = 0
    positive_answer_count: int = 0
    mapped_clause_types_detected: list[str] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    contract_type: str
    contract_type_label: str
    document_profile: DocumentProfile | None = None
    document_classification: DocumentClassificationInfo | None = None
    overall_risk_level: str
    overall_risk_score: int = Field(ge=0, le=100)
    risk_summary: str
    risk_counts: dict[str, int] = Field(default_factory=dict)
    missing_clauses: list[str] = Field(default_factory=list)
    review_clauses: list[str] = Field(default_factory=list)
    false_positive_checks: list[str] = Field(default_factory=list)
    review_focus: list[str] = Field(default_factory=list)
    cuad_coverage: CuadCoverage | None = None
    jurisdiction_warnings: list[dict[str, str]] = Field(default_factory=list)
    benchmark_notes: list[dict] = Field(default_factory=list)
    final_verdict: str | None = None
    verification_summary: VerificationSummary | None = None
    top_risks: list[AnalysisRiskItem]
    extraction_health: ExtractionHealth


class ClauseItem(BaseModel):
    id: int
    clause_type: str
    clause_title: str
    page_start: int
    page_end: int
    confidence_score: float = Field(ge=0.0, le=1.0)
    risk_level: str | None = None
    risk_score: int | None = None
    risk_summary: str | None = None


class ClauseListResponse(BaseModel):
    document_id: str
    clauses: list[ClauseItem]


class ClauseRiskItem(BaseModel):
    finding_id: int
    risk_category: str
    risk_level: str
    risk_score: int
    summary: str
    why_risky: str
    suggested_question: str
    page_number: int | None = None


class ClauseDetailResponse(BaseModel):
    id: int
    document_id: str
    clause_type: str
    clause_title: str
    clause_text: str
    normalized_text: str
    page_start: int
    page_end: int
    confidence_score: float = Field(ge=0.0, le=1.0)
    risks: list[ClauseRiskItem]


class ErrorResponse(BaseModel):
    detail: str
