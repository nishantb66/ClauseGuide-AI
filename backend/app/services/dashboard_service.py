from __future__ import annotations

from app.core.mongo import MongoStore

from app.models.clause import Clause, RiskFinding
from app.models.document import Document, DocumentStatus
from app.models.report import Report


class DashboardService:
    async def stats(self, session: MongoStore, *, owner_user_id: str) -> dict:
        documents = await session.find(Document, {"owner_user_id": owner_user_id})
        document_ids = [document.id for document in documents]
        related = {"document_id": {"$in": document_ids}}
        findings = await session.find(RiskFinding, related) if document_ids else []
        documents_uploaded = len(documents)
        documents_analyzed = sum(document.status == DocumentStatus.analyzed for document in documents)
        total_risks = len(findings)
        high_or_critical = sum(finding.risk_level in {"high", "critical"} for finding in findings)
        clauses_read = await session.count(Clause, related) if document_ids else 0
        reports_generated = await session.count(Report, related) if document_ids else 0
        avg_score = sum(finding.risk_score or 0 for finding in findings) / total_risks if findings else 0

        risk_breakdown = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for finding in findings:
            level = finding.risk_level
            if level in risk_breakdown:
                risk_breakdown[level] += 1

        latest_documents = [
            {
                "id": document.id,
                "title": document.title,
                "contract_type": document.contract_type,
                "status": document.status.value,
                "total_pages": document.total_pages,
                "uploaded_at": document.uploaded_at,
                "processed_at": document.processed_at,
            }
            for document in sorted(documents, key=lambda item: item.uploaded_at, reverse=True)[:5]
        ]

        return {
            "documents_uploaded": documents_uploaded,
            "documents_analyzed": documents_analyzed,
            "total_risks_detected": total_risks,
            "high_or_critical_risks": high_or_critical,
            "clauses_read": clauses_read,
            "reports_generated": reports_generated,
            "average_risk_score": round(float(avg_score or 0), 2),
            "latest_documents": latest_documents,
            "risk_level_breakdown": risk_breakdown,
        }
