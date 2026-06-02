from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clause import Clause, RiskFinding
from app.models.document import Document, DocumentStatus
from app.models.report import Report


class DashboardService:
    async def stats(self, session: AsyncSession, *, owner_user_id: str) -> dict:
        document_ids_query = select(Document.id).where(Document.owner_user_id == owner_user_id)

        documents_uploaded = await self._scalar_int(
            session, select(func.count(Document.id)).where(Document.owner_user_id == owner_user_id)
        )
        documents_analyzed = await self._scalar_int(
            session,
            select(func.count(Document.id)).where(
                Document.owner_user_id == owner_user_id,
                Document.status == DocumentStatus.analyzed,
            ),
        )
        total_risks = await self._scalar_int(
            session,
            select(func.count(RiskFinding.id)).where(
                RiskFinding.document_id.in_(document_ids_query)
            ),
        )
        high_or_critical = await self._scalar_int(
            session,
            select(func.count(RiskFinding.id)).where(
                RiskFinding.document_id.in_(document_ids_query),
                RiskFinding.risk_level.in_(["high", "critical"]),
            ),
        )
        clauses_read = await self._scalar_int(
            session, select(func.count(Clause.id)).where(Clause.document_id.in_(document_ids_query))
        )
        reports_generated = await self._scalar_int(
            session, select(func.count(Report.id)).where(Report.document_id.in_(document_ids_query))
        )
        avg_score = await session.scalar(
            select(func.avg(RiskFinding.risk_score)).where(
                RiskFinding.document_id.in_(document_ids_query)
            )
        )

        risk_breakdown = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        rows = await session.execute(
            select(RiskFinding.risk_level, func.count(RiskFinding.id))
            .where(RiskFinding.document_id.in_(document_ids_query))
            .group_by(RiskFinding.risk_level)
        )
        for level, count in rows.all():
            if level in risk_breakdown:
                risk_breakdown[level] = int(count or 0)

        latest_rows = await session.execute(
            select(Document)
            .where(Document.owner_user_id == owner_user_id)
            .order_by(Document.uploaded_at.desc())
            .limit(5)
        )
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
            for document in latest_rows.scalars().all()
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

    @staticmethod
    async def _scalar_int(session: AsyncSession, statement) -> int:
        return int((await session.scalar(statement)) or 0)
