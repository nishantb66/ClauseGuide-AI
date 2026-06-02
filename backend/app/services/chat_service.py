from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models.chat import ChatMessage, ChatSession
from app.models.clause import Clause, RiskFinding
from app.models.document import Document, DocumentPage, DocumentStatus
from app.services.citation_verifier import CitationVerifier
from app.services.confidence_scorer import ConfidenceScorer, ConfidenceSignals
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService
from app.services.legal_kb_service import LegalKnowledgeBase, get_legal_kb
from app.services.query_intent_detector import QueryIntentDetector
from app.services.retriever import HybridRetriever
from app.services.verification_service import VerificationService


class ChatService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.embedding_service = EmbeddingService()
        self.retriever = HybridRetriever(self.embedding_service)
        self.llm = LLMService()
        self.citation_verifier = CitationVerifier()
        self.intent_detector = QueryIntentDetector()
        self.confidence_scorer = ConfidenceScorer()
        self.kb: LegalKnowledgeBase = get_legal_kb()
        self.verifier = VerificationService(self.kb)

    async def ask(
        self,
        session: AsyncSession,
        *,
        document_id: str,
        question: str,
        session_id: str | None,
        owner_user_id: str | None = None,
    ) -> dict:
        document = await self._load_document(
            session, document_id=document_id, owner_user_id=owner_user_id
        )

        if session_id:
            chat_session = await session.get(ChatSession, session_id)
            if chat_session is None or chat_session.document_id != document.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
                )
        else:
            chat_session = ChatSession(document_id=document.id)
            session.add(chat_session)
            await session.flush()

        result = await self._answer_pipeline(
            session,
            document_id=document_id,
            question=question,
            session_id=chat_session.id,
            total_pages=document.total_pages,
        )

        await self._persist_messages(
            session=session,
            chat_session_id=chat_session.id,
            question=question,
            answer=result["answer"],
            sources=result.get("sources", []),
        )
        return result

    async def ask_ephemeral(
        self,
        session: AsyncSession,
        *,
        document_id: str,
        question: str,
        owner_user_id: str | None = None,
    ) -> dict:
        document = await self._load_document(
            session, document_id=document_id, owner_user_id=owner_user_id
        )
        return await self._answer_pipeline(
            session,
            document_id=document_id,
            question=question,
            session_id=None,
            total_pages=document.total_pages,
        )

    async def _answer_pipeline(
        self,
        session: AsyncSession,
        *,
        document_id: str,
        question: str,
        session_id: str | None,
        total_pages: int | None,
    ) -> dict:
        intent_result = self.intent_detector.detect(question)
        if intent_result.intent == "document_overview":
            response = await self._document_overview_response(
                session=session,
                document_id=document_id,
                session_id=session_id,
            )
            return self._with_chat_verification(
                response,
                total_pages=total_pages,
            )

        if intent_result.intent == "risk_summary":
            response = await self._risk_summary_response(
                session=session,
                document_id=document_id,
                session_id=session_id,
                required_clause_types=intent_result.required_clause_types,
            )
            return self._with_chat_verification(
                response,
                total_pages=total_pages,
            )

        retrieval_result = await self.retriever.retrieve(
            session,
            document_id=document_id,
            query=intent_result.rewritten_query,
            required_clause_types=intent_result.required_clause_types,
            top_k=8 if intent_result.intent == "risk_summary" else 6,
            semantic_pool=20,
            keyword_pool=20,
        )

        context_items = [
            {
                "page_number": item.page_number,
                "chunk_text": item.chunk_text,
                "clause_type": item.clause_type,
                "section_title": item.section_title,
            }
            for item in retrieval_result.items
        ]
        retrieved_context = [item["chunk_text"] for item in context_items]

        if not context_items or retrieval_result.retrieval_score < self.settings.retrieval_min_score_threshold:
            response = self._unsupported_response(
                intent=intent_result.intent,
                required_clause_types=intent_result.required_clause_types,
                session_id=session_id,
                retrieved_context=retrieved_context,
            )
            return self._with_chat_verification(
                response,
                total_pages=total_pages,
            )

        result = self.llm.answer_contract_question(question=question, context_items=context_items)
        sources = result.get("sources", [])

        citation_score = self.citation_verifier.score(
            sources=sources,
            retrieved_context=retrieved_context,
        )
        evidence_ok = citation_score >= self.settings.retrieval_min_citation_score
        clause_coverage_score = retrieval_result.intent_coverage_score
        intent_support_score = min(1.0, (intent_result.confidence_score + clause_coverage_score) / 2.0)

        confidence_result = self.confidence_scorer.score(
            ConfidenceSignals(
                retrieval_score=retrieval_result.retrieval_score,
                reranker_score=retrieval_result.reranker_score,
                citation_score=citation_score,
                clause_coverage_score=clause_coverage_score,
                intent_support_score=intent_support_score,
            )
        )

        lacks_intent_coverage = bool(intent_result.required_clause_types) and clause_coverage_score < 0.34
        if not evidence_ok or confidence_result.label == "not_enough_evidence" or lacks_intent_coverage:
            response = self._unsupported_response(
                intent=intent_result.intent,
                required_clause_types=intent_result.required_clause_types,
                session_id=session_id,
                retrieved_context=retrieved_context,
            )
            return self._with_chat_verification(
                response,
                total_pages=total_pages,
            )

        result["confidence_score"] = confidence_result.score
        result["confidence_label"] = confidence_result.label
        result["intent"] = intent_result.intent
        result["required_clause_types"] = intent_result.required_clause_types
        result["session_id"] = session_id
        result["retrieved_context"] = retrieved_context
        result["citation_score"] = citation_score
        return self._with_chat_verification(
            result,
            total_pages=total_pages,
        )

    def _with_chat_verification(self, result: dict, *, total_pages: int | None) -> dict:
        result["verification"] = self.verifier.verify_chat_answer(
            answer=str(result.get("answer", "")),
            sources=list(result.get("sources", [])),
            intent=str(result.get("intent", "unknown")),
            required_clause_types=list(result.get("required_clause_types", [])),
            citation_score=float(result.get("citation_score", 0.0) or 0.0),
            total_pages=total_pages,
            confidence_label=str(result.get("confidence_label", "low")),
        )
        return result

    async def _load_document(
        self, session: AsyncSession, *, document_id: str, owner_user_id: str | None = None
    ) -> Document:
        document = await session.get(Document, document_id)
        if document is None or (
            owner_user_id is not None and document.owner_user_id != owner_user_id
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        if document.status != DocumentStatus.analyzed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document is not processed yet. Run /process first.",
            )
        return document

    def _unsupported_response(
        self,
        *,
        intent: str,
        required_clause_types: list[str],
        session_id: str | None,
        retrieved_context: list[str],
    ) -> dict:
        return {
            "answer": "I could not find this information in the contract.",
            "confidence_score": 0.32,
            "confidence_label": "not_enough_evidence",
            "sources": [],
            "disclaimer": "This is not legal advice.",
            "intent": intent,
            "required_clause_types": required_clause_types,
            "session_id": session_id,
            "retrieved_context": retrieved_context,
        }

    async def _persist_messages(
        self,
        *,
        session: AsyncSession,
        chat_session_id: str,
        question: str,
        answer: str,
        sources: list[dict],
    ) -> None:
        session.add(ChatMessage(session_id=chat_session_id, role="user", message=question, sources_json=[]))
        session.add(
            ChatMessage(
                session_id=chat_session_id,
                role="assistant",
                message=answer,
                sources_json=sources,
            )
        )
        await session.commit()

    async def _document_overview_response(
        self,
        *,
        session: AsyncSession,
        document_id: str,
        session_id: str | None,
    ) -> dict:
        document = await session.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        clause_rows = await session.execute(
            select(Clause)
            .where(Clause.document_id == document_id)
            .order_by(Clause.page_start.asc(), Clause.id.asc())
        )
        clauses = clause_rows.scalars().all()

        finding_rows = await session.execute(
            select(RiskFinding)
            .where(RiskFinding.document_id == document_id)
            .order_by(RiskFinding.risk_score.desc())
            .limit(5)
        )
        findings = self._dedupe_findings(finding_rows.scalars().all())

        page_rows = await session.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number.asc())
            .limit(2)
        )
        pages = page_rows.scalars().all()

        clause_labels = self._top_clause_labels(clauses)
        risk_sentence = self._overview_risk_sentence(findings)
        first_page = next((page for page in pages if page.cleaned_text.strip()), None)
        source_text = self._snippet(first_page.cleaned_text if first_page else document.file_name, 280)

        answer_parts = [
            f"This appears to be a {self._pretty_label(document.contract_type or 'unknown')} with {document.total_pages} pages.",
        ]
        playbook = self.kb.playbook(document.contract_type or "unknown")
        if playbook.get("purpose"):
            answer_parts.append(f"Purpose: {playbook['purpose']}")
        if clause_labels:
            answer_parts.append(f"The main areas detected are {', '.join(clause_labels)}.")
        answer_parts.append(risk_sentence)
        review_focus = self.kb.review_focus(document.contract_type or "unknown")
        if review_focus:
            answer_parts.append(f"For this document type, I focus on {', '.join(review_focus[:5])}.")
        cuad_metadata = self.kb.cuad_metadata()
        if cuad_metadata:
            answer_parts.append(
                "Clause detection is supported by the local CUAD knowledge base "
                f"({cuad_metadata.get('contract_count', 0)} contracts, "
                f"{cuad_metadata.get('cuad_label_count', 0)} expert clause labels)."
            )
        answer_parts.append("I can also answer specific questions about payment, notice, termination, deposits, liability, or missing clauses.")

        sources = [
            {
                "page": first_page.page_number if first_page else 1,
                "clause_type": "document_overview",
                "evidence": source_text,
            }
        ]
        for clause in clauses[:2]:
            sources.append(
                {
                    "page": clause.page_start,
                    "clause_type": clause.clause_type,
                    "evidence": self._snippet(clause.clause_text, 240),
                }
            )

        return {
            "answer": " ".join(answer_parts),
            "confidence_score": 0.74 if clauses else 0.52,
            "confidence_label": "medium" if clauses else "low",
            "sources": sources[:3],
            "disclaimer": "This is not legal advice.",
            "intent": "document_overview",
            "required_clause_types": [],
            "session_id": session_id,
            "retrieved_context": [source["evidence"] for source in sources[:3]],
            "citation_score": 1.0,
        }

    async def _risk_summary_response(
        self,
        *,
        session: AsyncSession,
        document_id: str,
        session_id: str | None,
        required_clause_types: list[str],
    ) -> dict:
        rows = await session.execute(
            select(RiskFinding)
            .where(RiskFinding.document_id == document_id)
            .order_by(RiskFinding.risk_score.desc())
            .limit(5)
        )
        findings = self._dedupe_findings(rows.scalars().all())
        if not findings:
            return self._unsupported_response(
                intent="risk_summary",
                required_clause_types=required_clause_types,
                session_id=session_id,
                retrieved_context=[],
            )

        clause_ids = [finding.clause_id for finding in findings if finding.clause_id is not None]
        clause_map: dict[int, Clause] = {}
        if clause_ids:
            clause_rows = await session.execute(select(Clause).where(Clause.id.in_(clause_ids)))
            clause_map = {clause.id: clause for clause in clause_rows.scalars().all()}

        lead_items = []
        sources = []
        for finding in findings[:3]:
            clause = clause_map.get(finding.clause_id) if finding.clause_id else None
            clause_label = (clause.clause_type if clause else finding.risk_category).replace("_", " ")
            page = finding.page_number or (clause.page_start if clause else 1)
            lead_items.append(
                f"{clause_label}: {finding.summary} ({finding.risk_level}, page {page})"
            )
            sources.append(
                {
                    "page": page,
                    "clause_type": clause.clause_type if clause else finding.risk_category,
                    "evidence": finding.evidence_text[:260],
                }
            )

        answer = "Main risks found in this document: " + " ".join(
            f"{index}. {item}" for index, item in enumerate(lead_items, start=1)
        )
        return {
            "answer": answer,
            "confidence_score": 0.72,
            "confidence_label": "medium",
            "sources": sources,
            "disclaimer": "This is not legal advice.",
            "intent": "risk_summary",
            "required_clause_types": required_clause_types,
            "session_id": session_id,
            "retrieved_context": [source["evidence"] for source in sources],
            "citation_score": 1.0,
        }

    @staticmethod
    def _dedupe_findings(findings: list[RiskFinding]) -> list[RiskFinding]:
        output: list[RiskFinding] = []
        seen: set[tuple[str, str]] = set()
        for finding in findings:
            key = (finding.risk_category, " ".join(finding.summary.lower().split()))
            if key in seen:
                continue
            seen.add(key)
            output.append(finding)
        return output

    @staticmethod
    def _top_clause_labels(clauses: list[Clause]) -> list[str]:
        seen: list[str] = []
        for clause in clauses:
            label = ChatService._pretty_label(clause.clause_type)
            if label not in seen:
                seen.append(label)
            if len(seen) >= 5:
                break
        return seen

    @staticmethod
    def _overview_risk_sentence(findings: list[RiskFinding]) -> str:
        if not findings:
            return "No major deterministic risk was found in the extracted clauses, but human review is still recommended."

        top = findings[0]
        return (
            f"The highest-priority issue found is: {top.summary} "
            f"({top.risk_level} risk, score {top.risk_score})."
        )

    @staticmethod
    def _pretty_label(value: str) -> str:
        return value.replace("_", " ").title()

    @staticmethod
    def _snippet(text: str, max_length: int) -> str:
        normalized = " ".join(text.split()).strip()
        if len(normalized) <= max_length:
            return normalized
        return normalized[: max_length - 3].rstrip() + "..."
