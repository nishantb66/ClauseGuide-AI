from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.review_schema import ImportantPointsResponse, ReviewWorkspaceResponse
from app.services.document_review_service import DocumentReviewService

router = APIRouter(prefix="/documents", tags=["review-workspace"])
service = DocumentReviewService()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]


@router.get("/{document_id}/review-workspace", response_model=ReviewWorkspaceResponse)
async def get_review_workspace(
    document_id: str,
    session: SessionDep,
    current_user: UserDep,
) -> ReviewWorkspaceResponse:
    payload = await service.get_review_workspace(
        session,
        document_id=document_id,
        owner_user_id=current_user.id,
    )
    return ReviewWorkspaceResponse(**payload)


@router.get("/{document_id}/important-points", response_model=ImportantPointsResponse)
async def get_important_points(
    document_id: str,
    session: SessionDep,
    current_user: UserDep,
) -> ImportantPointsResponse:
    payload = await service.get_important_points(
        session,
        document_id=document_id,
        owner_user_id=current_user.id,
    )
    return ImportantPointsResponse(**payload)


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: str,
    session: SessionDep,
    current_user: UserDep,
) -> FileResponse:
    document, file_path = await service.get_document_file(
        session,
        document_id=document_id,
        owner_user_id=current_user.id,
    )
    return FileResponse(
        path=str(file_path),
        filename=document.file_name,
        media_type=(
            "application/pdf" if document.file_type == ".pdf" else "application/octet-stream"
        ),
    )
