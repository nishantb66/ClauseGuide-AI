from pydantic import BaseModel, Field


class VerificationCheck(BaseModel):
    check: str
    passed: bool
    detail: str


class VerificationResult(BaseModel):
    status: str
    score: float = Field(ge=0.0, le=1.0)
    checks_total: int = Field(ge=1)
    checks_passed: int = Field(ge=0)
    failed_checks: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    checks: list[VerificationCheck] = Field(default_factory=list)


class VerificationSummary(BaseModel):
    verified_count: int = 0
    needs_review_count: int = 0
    verification_rate: float = Field(ge=0.0, le=1.0, default=0.0)
