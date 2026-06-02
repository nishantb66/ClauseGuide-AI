from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models.clause import Clause, RiskFinding
from app.models.document import Document, DocumentStatus
from app.models.report import Report
from app.services.analysis_service import AnalysisService


class ReportService:
    amount_re = re.compile(r"(?:₹|rs\.?|inr)\s*[0-9][0-9,]*(?:\.[0-9]+)?", re.IGNORECASE)
    months_re = re.compile(r"\b\d{1,3}\s*(?:month|months)\b", re.IGNORECASE)
    days_re = re.compile(r"\b\d{1,3}\s*(?:day|days)\b", re.IGNORECASE)
    date_re = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")

    obligation_clause_types = {
        "termination",
        "notice_period",
        "payment",
        "liability",
        "confidentiality",
        "non_compete",
        "non_solicitation",
        "bond",
        "auto_renewal",
        "security_deposit",
        "lock_in",
        "scope_of_services",
        "service_level",
        "data_privacy",
        "compliance",
        "performance_obligations",
    }

    def __init__(self) -> None:
        self.settings = get_settings()
        self.analysis_service = AnalysisService()

    async def generate_report(
        self,
        session: AsyncSession,
        *,
        document_id: str,
        output_format: str,
        owner_user_id: str | None = None,
    ) -> dict:
        normalized_format = self._normalize_format(output_format)

        document = await session.get(Document, document_id)
        if document is None or (
            owner_user_id is not None and document.owner_user_id != owner_user_id
        ):
            raise ValueError("Document not found")
        if document.status != DocumentStatus.analyzed:
            raise ValueError("Document is not processed yet. Run /process first.")

        analysis = await self.analysis_service.get_analysis(
            session, document_id, owner_user_id=owner_user_id
        )

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
        )
        findings = finding_rows.scalars().all()

        payload = self._build_payload(
            document=document, analysis=analysis, clauses=clauses, findings=findings
        )
        content = (
            self._render_markdown(payload)
            if normalized_format == "markdown"
            else self._render_text(payload)
        )

        report_id = self._new_report_id()
        extension = "md" if normalized_format == "markdown" else "txt"
        file_name = self._build_file_name(document.title, report_id, extension)
        file_path = self.settings.report_path / file_name
        file_path.write_text(content, encoding="utf-8")

        report = Report(
            id=report_id,
            document_id=document_id,
            file_name=file_name,
            file_path=str(file_path),
            report_format=normalized_format,
            summary_json=payload,
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)

        return self._to_report_response(report)

    async def list_reports(
        self, session: AsyncSession, *, document_id: str, owner_user_id: str | None = None
    ) -> dict:
        document = await session.get(Document, document_id)
        if document is None or (
            owner_user_id is not None and document.owner_user_id != owner_user_id
        ):
            raise ValueError("Document not found")

        report_rows = await session.execute(
            select(Report)
            .where(Report.document_id == document_id)
            .order_by(Report.created_at.desc())
        )
        reports = report_rows.scalars().all()

        return {
            "document_id": document_id,
            "reports": [
                {
                    "report_id": report.id,
                    "report_format": report.report_format,
                    "file_name": report.file_name,
                    "download_url": self._download_url(report.id),
                    "created_at": report.created_at,
                }
                for report in reports
            ],
        }

    async def get_report_summary(
        self, session: AsyncSession, *, report_id: str, owner_user_id: str | None = None
    ) -> dict:
        report = await session.get(Report, report_id)
        if report is None:
            raise ValueError("Report not found")
        await self._ensure_report_owner(session, report, owner_user_id)

        return {
            "report_id": report.id,
            "document_id": report.document_id,
            "report_format": report.report_format,
            "created_at": report.created_at,
            "summary": report.summary_json,
        }

    async def get_report_file(
        self, session: AsyncSession, *, report_id: str, owner_user_id: str | None = None
    ) -> tuple[Report, Path]:
        report = await session.get(Report, report_id)
        if report is None:
            raise ValueError("Report not found")
        await self._ensure_report_owner(session, report, owner_user_id)

        file_path = Path(report.file_path)
        if not file_path.exists():
            raise ValueError("Report file not found on disk")

        return report, file_path

    async def _ensure_report_owner(
        self, session: AsyncSession, report: Report, owner_user_id: str | None
    ) -> None:
        if owner_user_id is None:
            return
        document = await session.get(Document, report.document_id)
        if document is None or document.owner_user_id != owner_user_id:
            raise ValueError("Report not found")

    def _build_payload(
        self,
        *,
        document: Document,
        analysis: dict,
        clauses: list[Clause],
        findings: list[RiskFinding],
    ) -> dict:
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        top_risks = analysis.get("top_risks", [])[:5]

        obligations = self._extract_obligations(clauses)
        highlights = self._extract_amounts_timelines(clauses)
        questions = self._build_questions(
            top_risks=top_risks, missing_clauses=analysis.get("missing_clauses", [])
        )

        confidence = self._report_confidence(
            clauses=clauses, findings=findings, top_risks=top_risks
        )
        summary_text = self._build_summary_text(analysis=analysis, top_risks=top_risks)

        source_pages = sorted(
            {
                int(risk.get("page", 0))
                for risk in top_risks
                if isinstance(risk.get("page"), int) and int(risk.get("page", 0)) > 0
            }
        )

        return {
            "generated_at": generated_at,
            "disclaimer": (
                "This is an AI contract analysis assistant output and not legal advice. "
                "Consult a qualified lawyer before making legal decisions."
            ),
            "document": {
                "document_id": document.id,
                "title": document.title,
                "file_name": document.file_name,
                "contract_type": analysis.get("contract_type", "unknown"),
                "total_pages": document.total_pages,
            },
            "analysis": {
                "overall_risk_level": analysis.get("overall_risk_level", "unknown"),
                "overall_risk_score": int(analysis.get("overall_risk_score", 0)),
                "summary": analysis.get("risk_summary") or summary_text,
                "missing_clauses": analysis.get("missing_clauses", []),
                "review_clauses": analysis.get("review_clauses", []),
                "risk_counts": analysis.get("risk_counts", {}),
                "document_profile": analysis.get("document_profile", {}),
                "document_classification": analysis.get("document_classification", {}),
                "false_positive_checks": analysis.get("false_positive_checks", []),
                "review_focus": analysis.get("review_focus", []),
                "cuad_coverage": analysis.get("cuad_coverage", {}),
                "jurisdiction_warnings": analysis.get("jurisdiction_warnings", []),
                "benchmark_notes": analysis.get("benchmark_notes", []),
                "final_verdict": analysis.get("final_verdict"),
            },
            "top_risks": top_risks,
            "important_obligations": obligations,
            "important_amounts_and_timelines": highlights,
            "questions_to_ask": questions,
            "confidence": confidence,
            "sources": {
                "document_file": document.file_name,
                "risk_pages": source_pages,
                "total_clauses_extracted": len(clauses),
                "total_risk_findings": len(findings),
            },
        }

    def _render_markdown(self, payload: dict) -> str:
        doc = payload["document"]
        analysis = payload["analysis"]

        lines: list[str] = []
        lines.append("# ClauseGuide AI Risk Report")
        lines.append("")
        lines.append(f"Generated at: {payload['generated_at']}")
        lines.append("")
        lines.append("## Disclaimer")
        lines.append(payload["disclaimer"])
        lines.append("")
        lines.append("## Contract Snapshot")
        lines.append(f"- Document: {doc['title']}")
        lines.append(f"- File Name: {doc['file_name']}")
        lines.append(f"- Contract Type: {self._pretty_label(doc['contract_type'])}")
        lines.append(f"- Total Pages: {doc['total_pages']}")
        lines.append(f"- Overall Risk Score: {analysis['overall_risk_score']}")
        lines.append(f"- Overall Risk Level: {analysis['overall_risk_level']}")
        lines.append("")
        lines.append("## Executive Summary")
        lines.append(analysis["summary"])
        if analysis.get("final_verdict"):
            lines.append("")
            lines.append(f"**Final verdict:** {analysis['final_verdict']}")
        lines.append("")

        profile = analysis.get("document_profile") or {}
        if profile:
            lines.append("## Document-Specific Context")
            lines.append(f"- Purpose: {profile.get('purpose', 'Unknown')}")
            lines.append(f"- Likely Reviewing Role: {profile.get('likely_user_role', 'Unknown')}")
            lines.append(f"- Likely Stronger Party: {profile.get('stronger_party', 'Unknown')}")
            parties = profile.get("detected_parties") or []
            lines.append(f"- Detected Parties: {', '.join(parties) if parties else 'Not found'}")
            lines.append(
                f"- Governing Law / Jurisdiction: {profile.get('governing_law') or 'Not found'}"
            )
            lines.append("")

        classification = analysis.get("document_classification") or {}
        if classification:
            lines.append("## Document Classification")
            lines.append(
                f"- Primary Type: {self._pretty_label(str(classification.get('primary_document_type', 'unknown')))}"
            )
            secondaries = classification.get("secondary_document_types") or []
            if secondaries:
                lines.append(
                    "- Secondary Types: "
                    + ", ".join(self._pretty_label(str(item)) for item in secondaries)
                )
            lines.append(f"- Template/Sample: {bool(classification.get('is_template'))}")
            lines.append(
                f"- Executed Agreement: {bool(classification.get('is_executed_agreement'))}"
            )
            lines.append(
                f"- Multiple Document Types: {bool(classification.get('contains_multiple_document_types'))}"
            )
            sections = classification.get("sections") or []
            if sections:
                lines.append("- Sections:")
                for section in sections[:8]:
                    lines.append(
                        "  - "
                        f"{self._pretty_label(str(section.get('document_type', 'unknown')))} "
                        f"(pages {section.get('page_start')}-{section.get('page_end')}): "
                        f"{section.get('title', '')}"
                    )
            lines.append("")

        focus = analysis.get("review_focus", [])
        if focus:
            lines.append("## Document-Type Review Focus")
            for item in focus:
                lines.append(f"- {self._pretty_label(str(item))}")
            lines.append("")

        cuad = analysis.get("cuad_coverage") or {}
        if cuad.get("enabled"):
            lines.append("## CUAD-Backed Clause Knowledge")
            lines.append(f"- Source: {cuad.get('source', 'theatticusproject/cuad')}")
            lines.append(f"- License: {cuad.get('license', 'CC BY 4.0')}")
            lines.append(f"- Contracts Indexed: {cuad.get('contract_count', 0)}")
            lines.append(f"- Expert Clause Labels: {cuad.get('cuad_label_count', 0)}")
            lines.append(f"- Positive Annotated Answers: {cuad.get('positive_answer_count', 0)}")
            mapped = cuad.get("mapped_clause_types_detected") or []
            if mapped:
                lines.append(
                    "- CUAD-Mapped Clause Types Detected: "
                    + ", ".join(self._pretty_label(str(item)) for item in mapped)
                )
            lines.append("")

        jurisdiction_warnings = analysis.get("jurisdiction_warnings", [])
        if jurisdiction_warnings:
            lines.append("## India-Specific Issue Spotting")
            for warning in jurisdiction_warnings:
                lines.append(
                    f"- {warning.get('warning', '')} {warning.get('recommended_check', '')}".strip()
                )
            lines.append("")

        benchmarks = analysis.get("benchmark_notes", [])
        if benchmarks:
            lines.append("## Benchmark Comparison Notes")
            for benchmark in benchmarks:
                normal = ", ".join(
                    self._pretty_label(str(item)) for item in benchmark.get("normal_structure", [])
                )
                red_flags = ", ".join(
                    self._pretty_label(str(item)) for item in benchmark.get("red_flags", [])
                )
                lines.append(f"- Normal structure: {normal}")
                lines.append(f"- Typical red flags checked: {red_flags}")
            lines.append("")

        missing = analysis.get("missing_clauses", [])
        if missing:
            lines.append("## Missing Important Clauses")
            for clause in missing:
                lines.append(f"- {self._pretty_label(clause)}")
            lines.append("")

        review_items = analysis.get("review_clauses", [])
        if review_items:
            lines.append("## Recommended Review Items")
            for clause in review_items:
                lines.append(f"- {self._pretty_label(clause)}")
            lines.append("")

        checks = analysis.get("false_positive_checks", [])
        if checks:
            lines.append("## False-Positive Guardrails Applied")
            for check in checks:
                lines.append(f"- {check}")
            lines.append("")

        lines.append("## Top Risky Clauses")
        if payload["top_risks"]:
            for index, risk in enumerate(payload["top_risks"], start=1):
                lines.append(
                    f"### {index}. {self._pretty_label(risk['clause_type'])} "
                    f"(Risk: {risk['risk_level']} | Score: {risk['risk_score']})"
                )
                lines.append(f"- Summary: {risk['summary']}")
                lines.append(f"- Plain English: {risk.get('plain_language') or risk['why_risky']}")
                lines.append(f"- Why Risky: {risk['why_risky']}")
                lines.append(f"- Suggested Question: {risk['suggested_question']}")
                lines.append(f"- Source: Page {risk['page']}")
                lines.append("")
        else:
            lines.append("- No major high-confidence risks were identified in this phase.")
            lines.append("")

        lines.append("## Important Obligations")
        if payload["important_obligations"]:
            for item in payload["important_obligations"]:
                lines.append(
                    f"- {self._pretty_label(item['clause_type'])} (Page {item['page']}): {item['obligation']}"
                )
        else:
            lines.append("- No obligation highlights were extracted.")
        lines.append("")

        lines.append("## Important Amounts and Timelines")
        if payload["important_amounts_and_timelines"]:
            for item in payload["important_amounts_and_timelines"]:
                lines.append(
                    f"- {self._pretty_label(item['kind'])}: {item['value']} (Page {item['page']})"
                )
        else:
            lines.append("- No explicit amounts or timelines were detected.")
        lines.append("")

        lines.append("## Questions to Ask Before Signing")
        for question in payload["questions_to_ask"]:
            lines.append(f"- {question}")
        lines.append("")

        lines.append("## AI Confidence")
        lines.append(
            f"- Confidence Score: {payload['confidence']['score']:.2f} "
            f"({payload['confidence']['label']})"
        )
        lines.append(
            "- Confidence is based on extraction confidence, risk-finding confidence, and source coverage."
        )
        lines.append("")

        lines.append("## Sources")
        lines.append(f"- Contract file: {payload['sources']['document_file']}")
        risk_pages = payload["sources"].get("risk_pages", [])
        if risk_pages:
            lines.append(f"- Referenced pages: {', '.join(str(page) for page in risk_pages)}")
        else:
            lines.append("- Referenced pages: none")
        lines.append(f"- Clauses extracted: {payload['sources']['total_clauses_extracted']}")
        lines.append(f"- Risk findings: {payload['sources']['total_risk_findings']}")

        return "\n".join(lines).strip() + "\n"

    def _render_text(self, payload: dict) -> str:
        markdown = self._render_markdown(payload)
        return markdown.replace("# ", "").replace("## ", "").replace("### ", "")

    def _extract_obligations(self, clauses: list[Clause]) -> list[dict]:
        obligations: list[dict] = []
        for clause in clauses:
            if clause.clause_type not in self.obligation_clause_types:
                continue
            snippet = self._snippet(clause.clause_text, 220)
            obligations.append(
                {
                    "clause_type": clause.clause_type,
                    "page": clause.page_start,
                    "obligation": snippet,
                }
            )
            if len(obligations) >= 8:
                break
        return obligations

    def _extract_amounts_timelines(self, clauses: list[Clause]) -> list[dict]:
        highlights: list[dict] = []
        seen: set[tuple[str, str, int]] = set()

        for clause in clauses:
            page = clause.page_start
            text = clause.clause_text

            for matcher, kind in (
                (self.amount_re, "amount"),
                (self.months_re, "duration_months"),
                (self.days_re, "duration_days"),
                (self.date_re, "date"),
            ):
                for match in matcher.finditer(text):
                    value = self._normalize_spaces(match.group(0))
                    key = (kind, value.lower(), page)
                    if key in seen:
                        continue
                    highlights.append({"kind": kind, "value": value, "page": page})
                    seen.add(key)
                    if len(highlights) >= 12:
                        return highlights

        return highlights

    def _build_questions(self, *, top_risks: list[dict], missing_clauses: list[str]) -> list[str]:
        questions: list[str] = []
        seen: set[str] = set()

        for risk in top_risks:
            question = self._normalize_spaces(str(risk.get("suggested_question", "")))
            if not question:
                continue
            lowered = question.lower()
            if lowered in seen:
                continue
            questions.append(question)
            seen.add(lowered)
            if len(questions) >= 7:
                break

        for clause in missing_clauses:
            question = f"Can we add a clear {self._pretty_label(clause).lower()} clause to reduce ambiguity?"
            lowered = question.lower()
            if lowered in seen:
                continue
            questions.append(question)
            seen.add(lowered)
            if len(questions) >= 10:
                break

        if not questions:
            questions.append("Can we review this contract with legal counsel before signing?")
        return questions

    def _report_confidence(
        self, *, clauses: list[Clause], findings: list[RiskFinding], top_risks: list[dict]
    ) -> dict:
        clause_conf = sum(clause.confidence_score for clause in clauses) / max(1, len(clauses))
        finding_conf = sum(finding.confidence_score for finding in findings) / max(1, len(findings))
        citation_coverage = sum(
            1 for risk in top_risks if isinstance(risk.get("page"), int) and risk["page"] > 0
        )
        source_conf = citation_coverage / max(1, len(top_risks)) if top_risks else 0.5

        score = (0.45 * clause_conf) + (0.45 * finding_conf) + (0.10 * source_conf)
        score = max(0.0, min(1.0, round(score, 4)))

        if score >= 0.80:
            label = "high"
        elif score >= 0.60:
            label = "medium"
        elif score >= 0.40:
            label = "low"
        else:
            label = "not_enough_evidence"

        return {"score": score, "label": label}

    def _build_summary_text(self, *, analysis: dict, top_risks: list[dict]) -> str:
        risk_level = str(analysis.get("overall_risk_level", "unknown"))
        risk_score = int(analysis.get("overall_risk_score", 0))
        if top_risks:
            leading = "; ".join(self._normalize_spaces(risk["summary"]) for risk in top_risks[:2])
        else:
            leading = "no major risk findings were detected in the current extraction scope"

        return (
            f"The contract is assessed as {risk_level} risk with a score of {risk_score}. "
            f"Key drivers: {leading}."
        )

    def _to_report_response(self, report: Report) -> dict:
        return {
            "report_id": report.id,
            "document_id": report.document_id,
            "report_format": report.report_format,
            "file_name": report.file_name,
            "download_url": self._download_url(report.id),
            "created_at": report.created_at,
        }

    def _download_url(self, report_id: str) -> str:
        return f"{self.settings.api_prefix}/reports/{report_id}/download"

    @staticmethod
    def _normalize_format(output_format: str) -> str:
        normalized = (output_format or "").strip().lower()
        if normalized in {"markdown", "md"}:
            return "markdown"
        if normalized in {"text", "txt"}:
            return "text"
        raise ValueError("Unsupported report format. Allowed values: markdown, text")

    @staticmethod
    def _new_report_id() -> str:
        import uuid

        return str(uuid.uuid4())

    @staticmethod
    def _build_file_name(document_title: str, report_id: str, extension: str) -> str:
        title = re.sub(r"[^A-Za-z0-9._-]+", "_", document_title).strip("_")
        if not title:
            title = "contract"
        return f"{title}_report_{report_id[:8]}.{extension}"

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        return " ".join(text.split()).strip()

    def _snippet(self, text: str, max_length: int) -> str:
        normalized = self._normalize_spaces(text)
        if len(normalized) <= max_length:
            return normalized
        return normalized[: max_length - 3].rstrip() + "..."

    @staticmethod
    def _pretty_label(value: str) -> str:
        return value.replace("_", " ").title()
