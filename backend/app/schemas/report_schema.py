from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReportGenerateRequest(BaseModel):
    output_format: Literal["markdown", "text"] = "markdown"


class ReportGenerateResponse(BaseModel):
    report_id: str
    document_id: str
    report_format: str
    file_name: str
    download_url: str
    created_at: datetime


class ReportListItem(BaseModel):
    report_id: str
    report_format: str
    file_name: str
    download_url: str
    created_at: datetime


class ReportListResponse(BaseModel):
    document_id: str
    reports: list[ReportListItem]


class ReportSummaryResponse(BaseModel):
    report_id: str
    document_id: str
    report_format: str
    created_at: datetime
    summary: dict = Field(default_factory=dict)
