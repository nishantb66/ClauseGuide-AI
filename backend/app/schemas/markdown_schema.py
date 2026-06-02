from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field

from app.schemas.review_schema import HighlightRect


class PdfLineItem(BaseModel):
    id: str
    page: int
    text: str
    rects: list[HighlightRect]


class MarkdownWorkspaceCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    document_id: str | None = None


class MarkdownNoteCreate(BaseModel):
    page_number: int = Field(ge=1)
    selected_text: str = Field(min_length=1, max_length=5000)
    rects: list[HighlightRect] = Field(default_factory=list)
    note_html: str = Field(default="", max_length=20000)
    note_markdown: str = Field(default="", max_length=20000)
    color: str = Field(default="yellow", max_length=24)


class MarkdownNoteUpdate(BaseModel):
    note_html: str = Field(default="", max_length=20000)
    note_markdown: str = Field(default="", max_length=20000)
    color: str = Field(default="yellow", max_length=24)


class MarkdownNoteItem(BaseModel):
    id: str
    workspace_id: str
    page_number: int
    selected_text: str
    rects: list[HighlightRect]
    note_html: str
    note_markdown: str
    color: str
    created_at: datetime
    updated_at: datetime


class MarkdownWorkspaceItem(BaseModel):
    id: str
    title: str
    document_id: str | None
    document_title: str | None
    file_name: str | None
    file_type: str | None
    file_url: str | None
    total_pages: int
    notes_count: int
    created_at: datetime
    updated_at: datetime


class MarkdownWorkspaceDetail(MarkdownWorkspaceItem):
    notes: list[MarkdownNoteItem]
    lines: list[PdfLineItem]
