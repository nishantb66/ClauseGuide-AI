from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.evaluation_schema import (
    EvaluationRunListResponse,
    EvaluationRunRequest,
    EvaluationRunResponse,
)
from app.services.evaluation_service import EvaluationService

router = APIRouter(prefix="/documents", tags=["evaluations"])
service = EvaluationService()


@router.post("/{document_id}/evaluations/run", response_model=EvaluationRunResponse)
async def run_evaluation(
    document_id: str,
    payload: EvaluationRunRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> EvaluationRunResponse:
    try:
        result = await service.run_evaluation(
            session,
            document_id=document_id,
            run_label=payload.run_label,
            use_ragas=payload.use_ragas,
            test_cases=payload.test_cases,
            owner_user_id=current_user.id,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            code = status.HTTP_404_NOT_FOUND
        elif "not processed" in detail.lower():
            code = status.HTTP_409_CONFLICT
        else:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail) from exc

    return EvaluationRunResponse(**result)


@router.get("/{document_id}/evaluations", response_model=EvaluationRunListResponse)
async def list_evaluation_runs(
    document_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> EvaluationRunListResponse:
    try:
        result = await service.list_runs(
            session, document_id=document_id, owner_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return EvaluationRunListResponse(**result)
