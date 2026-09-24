from __future__ import annotations

from datetime import datetime, timezone
import fitz
from fastapi import HTTPException, status
from app.core.mongo import MongoStore, read_file_bytes

from app.models.document import Document
from app.models.markdown import MarkdownNote, MarkdownWorkspace
from app.schemas.markdown_schema import MarkdownNoteCreate, MarkdownNoteUpdate, MarkdownWorkspaceCreate


class MarkdownService:
    """Persistent PDF-anchored note workspaces for user-authored Markdown review."""

    async def list_workspaces(self, session: MongoStore, *, owner_user_id: str) -> list[dict]:
        workspaces = await session.find(MarkdownWorkspace, {"owner_user_id": owner_user_id}, sort=[("updated_at", -1)])
        items = []
        for workspace in workspaces:
            document = await session.get(Document, workspace.document_id) if workspace.document_id else None
            count = await session.count(MarkdownNote, {"workspace_id": workspace.id})
            items.append(self._workspace_item(workspace, document, count))
        return items

    async def create_workspace(
        self,
        session: MongoStore,
        payload: MarkdownWorkspaceCreate,
        *,
        owner_user_id: str,
    ) -> dict:
        document = None
        if payload.document_id:
            document = await self._load_document(session, payload.document_id, owner_user_id=owner_user_id)
            workspace = await session.one(MarkdownWorkspace, {"owner_user_id": owner_user_id, "document_id": document.id})
            if workspace:
                return await self.get_workspace(session, workspace.id, owner_user_id=owner_user_id)

        title = payload.title or (f"Notes: {document.title}" if document else "Untitled Markdown workspace")
        workspace = MarkdownWorkspace(
            owner_user_id=owner_user_id,
            document_id=document.id if document else None,
            title=title[:255],
        )
        session.add(workspace)
        await session.commit()
        await session.refresh(workspace)
        return await self.get_workspace(session, workspace.id, owner_user_id=owner_user_id)

    async def get_workspace(self, session: MongoStore, workspace_id: str, *, owner_user_id: str) -> dict:
        workspace = await self._load_workspace(session, workspace_id, owner_user_id=owner_user_id)
        document = None
        lines: list[dict] = []
        if workspace.document_id:
            document = await self._load_document(session, workspace.document_id, owner_user_id=owner_user_id)
            lines = await self.get_pdf_lines(session, document.id, owner_user_id=owner_user_id)

        return {
            **self._workspace_item(workspace, document, len(workspace.notes)),
            "notes": [self._note_item(note) for note in sorted(workspace.notes, key=lambda item: item.created_at)],
            "lines": lines,
        }

    async def get_or_create_for_document(
        self, session: MongoStore, document_id: str, *, owner_user_id: str
    ) -> dict:
        return await self.create_workspace(
            session,
            MarkdownWorkspaceCreate(document_id=document_id),
            owner_user_id=owner_user_id,
        )

    async def create_note(
        self,
        session: MongoStore,
        workspace_id: str,
        payload: MarkdownNoteCreate,
        *,
        owner_user_id: str,
    ) -> dict:
        workspace = await self._load_workspace(session, workspace_id, owner_user_id=owner_user_id)
        note = MarkdownNote(
            workspace_id=workspace.id,
            page_number=payload.page_number,
            selected_text=payload.selected_text.strip(),
            rects=[rect.model_dump() for rect in payload.rects],
            note_html=payload.note_html,
            note_markdown=payload.note_markdown,
            color=payload.color,
        )
        workspace.updated_at = datetime.now(timezone.utc)
        session.add(note)
        await session.commit()
        await session.refresh(note)
        return self._note_item(note)

    async def update_note(
        self,
        session: MongoStore,
        workspace_id: str,
        note_id: str,
        payload: MarkdownNoteUpdate,
        *,
        owner_user_id: str,
    ) -> dict:
        workspace = await self._load_workspace(session, workspace_id, owner_user_id=owner_user_id)
        note = next((item for item in workspace.notes if item.id == note_id), None)
        if note is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
        now = datetime.now(timezone.utc)
        note.note_html = payload.note_html
        note.note_markdown = payload.note_markdown
        note.color = payload.color
        note.updated_at = now
        workspace.updated_at = now
        await session.commit()
        await session.refresh(note)
        return self._note_item(note)

    async def delete_note(
        self,
        session: MongoStore,
        workspace_id: str,
        note_id: str,
        *,
        owner_user_id: str,
    ) -> dict[str, str]:
        workspace = await self._load_workspace(session, workspace_id, owner_user_id=owner_user_id)
        note = next((item for item in workspace.notes if item.id == note_id), None)
        if note is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
        await session.delete(note)
        workspace.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return {"status": "deleted"}

    async def get_pdf_lines(self, session: MongoStore, document_id: str, *, owner_user_id: str) -> list[dict]:
        document = await self._load_document(session, document_id, owner_user_id=owner_user_id)
        if document.file_type != ".pdf":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Markdown PDF notes currently require a PDF document.")
        file_bytes = await read_file_bytes(document.id)
        if not file_bytes:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found")

        lines: list[dict] = []
        with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
            for page_index, page in enumerate(pdf, start=1):
                page_rect = page.rect
                page_dict = page.get_text("dict", sort=True)
                line_index = 0
                for block in page_dict.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        spans = [span.get("text", "") for span in line.get("spans", [])]
                        text = "".join(spans).strip()
                        if len(text) < 3:
                            continue
                        x0, y0, x1, y1 = line.get("bbox", [0, 0, 0, 0])
                        if x1 <= x0 or y1 <= y0:
                            continue
                        line_index += 1
                        lines.append(
                            {
                                "id": f"p{page_index}-l{line_index}",
                                "page": page_index,
                                "text": text,
                                "rects": [
                                    {
                                        "page": page_index,
                                        "x0": round(float(x0), 2),
                                        "y0": round(float(y0), 2),
                                        "x1": round(float(x1), 2),
                                        "y1": round(float(y1), 2),
                                        "page_width": round(page_rect.width, 2),
                                        "page_height": round(page_rect.height, 2),
                                    }
                                ],
                            }
                        )
        return lines

    async def _load_workspace(self, session: MongoStore, workspace_id: str, *, owner_user_id: str) -> MarkdownWorkspace:
        workspace = await session.one(MarkdownWorkspace, {"id": workspace_id, "owner_user_id": owner_user_id})
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Markdown workspace not found")
        workspace.notes = await session.find(MarkdownNote, {"workspace_id": workspace_id}, sort=[("created_at", 1)])
        return workspace

    async def _load_document(self, session: MongoStore, document_id: str, *, owner_user_id: str) -> Document:
        document = await session.get(Document, document_id)
        if document is None or document.owner_user_id != owner_user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return document

    @staticmethod
    def _workspace_item(workspace: MarkdownWorkspace, document: Document | None, notes_count: int) -> dict:
        return {
            "id": workspace.id,
            "title": workspace.title,
            "document_id": workspace.document_id,
            "document_title": document.title if document else None,
            "file_name": document.file_name if document else None,
            "file_type": document.file_type if document else None,
            "file_url": f"/api/documents/{document.id}/file" if document else None,
            "total_pages": document.total_pages if document else 0,
            "notes_count": int(notes_count or 0),
            "created_at": workspace.created_at,
            "updated_at": workspace.updated_at,
        }

    @staticmethod
    def _note_item(note: MarkdownNote) -> dict:
        return {
            "id": note.id,
            "workspace_id": note.workspace_id,
            "page_number": note.page_number,
            "selected_text": note.selected_text,
            "rects": note.rects or [],
            "note_html": note.note_html,
            "note_markdown": note.note_markdown,
            "color": note.color,
            "created_at": note.created_at,
            "updated_at": note.updated_at,
        }
