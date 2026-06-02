from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    run_label: Mapped[str] = mapped_column(String(120), default="default")
    ragas_enabled: Mapped[bool] = mapped_column(default=False)
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    document: Mapped["Document"] = relationship(back_populates="evaluation_runs")
    results: Mapped[list["EvaluationResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)

    question: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_answer: Mapped[str] = mapped_column(Text)

    expected_source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_clause_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expected_risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)

    actual_sources_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    retrieved_context_json: Mapped[list[str]] = mapped_column(JSON, default=list)

    faithfulness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_relevancy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_precision_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_recall_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    amount_accuracy_score: Mapped[float] = mapped_column(Float, default=0.0)
    date_accuracy_score: Mapped[float] = mapped_column(Float, default=0.0)
    clause_classification_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level_accuracy_score: Mapped[float] = mapped_column(Float, default=0.0)
    citation_exact_match_score: Mapped[float] = mapped_column(Float, default=0.0)
    unsupported_refusal_score: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    run: Mapped[EvaluationRun] = relationship(back_populates="results")
    document: Mapped["Document"] = relationship(back_populates="evaluation_results")


from app.models.document import Document  # noqa: E402  # isort: skip
