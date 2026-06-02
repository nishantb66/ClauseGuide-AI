from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.document_schema import AnalysisResponse
from app.services.analysis_service import AnalysisService

router = APIRouter(prefix="/documents", tags=["analysis"])
service = AnalysisService()


@router.get("/{document_id}/analysis", response_model=AnalysisResponse)
async def get_analysis(
    document_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AnalysisResponse:
    try:
        analysis = await service.get_analysis(
            session, document_id, owner_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return AnalysisResponse(**analysis)
