from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.document_schema import ClauseDetailResponse, ClauseListResponse
from app.services.clause_service import ClauseService

router = APIRouter(prefix="/documents", tags=["clauses"])
service = ClauseService()


@router.get("/{document_id}/clauses", response_model=ClauseListResponse)
async def list_clauses(
    document_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ClauseListResponse:
    try:
        payload = await service.list_clauses(
            session, document_id, owner_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ClauseListResponse(**payload)


@router.get("/{document_id}/clauses/{clause_id}", response_model=ClauseDetailResponse)
async def get_clause_detail(
    document_id: str,
    clause_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ClauseDetailResponse:
    try:
        payload = await service.get_clause_detail(
            session, document_id, clause_id, owner_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ClauseDetailResponse(**payload)
