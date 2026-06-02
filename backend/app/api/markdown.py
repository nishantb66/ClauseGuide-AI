from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.markdown_schema import (
    MarkdownNoteCreate,
    MarkdownNoteItem,
    MarkdownNoteUpdate,
    MarkdownWorkspaceCreate,
    MarkdownWorkspaceDetail,
    MarkdownWorkspaceItem,
    PdfLineItem,
)
from app.services.markdown_service import MarkdownService

router = APIRouter(prefix="/markdown", tags=["markdown-notes"])
service = MarkdownService()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]


@router.get("/workspaces", response_model=list[MarkdownWorkspaceItem])
async def list_markdown_workspaces(session: SessionDep, current_user: UserDep) -> list[MarkdownWorkspaceItem]:
    payload = await service.list_workspaces(session, owner_user_id=current_user.id)
    return [MarkdownWorkspaceItem(**item) for item in payload]


@router.post("/workspaces", response_model=MarkdownWorkspaceDetail, status_code=status.HTTP_201_CREATED)
async def create_markdown_workspace(
    payload: MarkdownWorkspaceCreate,
    session: SessionDep,
    current_user: UserDep,
) -> MarkdownWorkspaceDetail:
    workspace = await service.create_workspace(session, payload, owner_user_id=current_user.id)
    return MarkdownWorkspaceDetail(**workspace)


@router.get("/workspaces/{workspace_id}", response_model=MarkdownWorkspaceDetail)
async def get_markdown_workspace(
    workspace_id: str,
    session: SessionDep,
    current_user: UserDep,
) -> MarkdownWorkspaceDetail:
    workspace = await service.get_workspace(session, workspace_id, owner_user_id=current_user.id)
    return MarkdownWorkspaceDetail(**workspace)


@router.post("/documents/{document_id}/workspace", response_model=MarkdownWorkspaceDetail)
async def get_or_create_document_workspace(
    document_id: str,
    session: SessionDep,
    current_user: UserDep,
) -> MarkdownWorkspaceDetail:
    workspace = await service.get_or_create_for_document(session, document_id, owner_user_id=current_user.id)
    return MarkdownWorkspaceDetail(**workspace)


@router.get("/documents/{document_id}/lines", response_model=list[PdfLineItem])
async def get_document_pdf_lines(
    document_id: str,
    session: SessionDep,
    current_user: UserDep,
) -> list[PdfLineItem]:
    lines = await service.get_pdf_lines(session, document_id, owner_user_id=current_user.id)
    return [PdfLineItem(**line) for line in lines]


@router.post("/workspaces/{workspace_id}/notes", response_model=MarkdownNoteItem, status_code=status.HTTP_201_CREATED)
async def create_markdown_note(
    workspace_id: str,
    payload: MarkdownNoteCreate,
    session: SessionDep,
    current_user: UserDep,
) -> MarkdownNoteItem:
    note = await service.create_note(session, workspace_id, payload, owner_user_id=current_user.id)
    return MarkdownNoteItem(**note)


@router.patch("/workspaces/{workspace_id}/notes/{note_id}", response_model=MarkdownNoteItem)
async def update_markdown_note(
    workspace_id: str,
    note_id: str,
    payload: MarkdownNoteUpdate,
    session: SessionDep,
    current_user: UserDep,
) -> MarkdownNoteItem:
    note = await service.update_note(session, workspace_id, note_id, payload, owner_user_id=current_user.id)
    return MarkdownNoteItem(**note)


@router.delete("/workspaces/{workspace_id}/notes/{note_id}")
async def delete_markdown_note(
    workspace_id: str,
    note_id: str,
    session: SessionDep,
    current_user: UserDep,
) -> dict[str, str]:
    return await service.delete_note(session, workspace_id, note_id, owner_user_id=current_user.id)
