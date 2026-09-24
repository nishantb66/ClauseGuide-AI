from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.core.mongo import MongoStore

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.mongo import file_chunks
from app.models.user import User
from app.schemas.review_schema import ImportantPointsResponse, ReviewWorkspaceResponse
from app.services.document_review_service import DocumentReviewService

router = APIRouter(prefix="/documents", tags=["review-workspace"])
service = DocumentReviewService()
SessionDep = Annotated[MongoStore, Depends(get_session)]
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
) -> StreamingResponse:
    document = await service.get_document_file(
        session,
        document_id=document_id,
        owner_user_id=current_user.id,
    )
    return StreamingResponse(
        file_chunks(document.id),
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(document.file_name, safe='')}"},
        media_type=(
            "application/pdf" if document.file_type == ".pdf" else "application/octet-stream"
        ),
    )
