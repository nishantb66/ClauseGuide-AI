from __future__ import annotations

from pydantic import BaseModel


class DashboardStats(BaseModel):
    documents_uploaded: int
    documents_analyzed: int
    total_risks_detected: int
    high_or_critical_risks: int
    clauses_read: int
    reports_generated: int
    average_risk_score: float
    latest_documents: list[dict]
    risk_level_breakdown: dict[str, int]
