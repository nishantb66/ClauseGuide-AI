from types import SimpleNamespace

from app.services.report_service import ReportService


def test_normalize_report_format() -> None:
    service = ReportService()

    assert service._normalize_format("markdown") == "markdown"
    assert service._normalize_format("md") == "markdown"
    assert service._normalize_format("text") == "text"
    assert service._normalize_format("txt") == "text"


def test_report_payload_and_render() -> None:
    service = ReportService()

    document = SimpleNamespace(
        id="doc_1",
        title="Employment Bond Contract",
        file_name="bond.pdf",
        total_pages=6,
    )
    analysis = {
        "contract_type": "employment_bond",
        "overall_risk_level": "high",
        "overall_risk_score": 74,
        "missing_clauses": ["termination"],
        "top_risks": [
            {
                "clause_type": "bond",
                "risk_level": "high",
                "risk_score": 82,
                "summary": "Fixed bond amount with no pro-rata reduction.",
                "why_risky": "No proportional reduction language is found.",
                "suggested_question": "Can the bond amount be reduced based on time served?",
                "page": 3,
            }
        ],
    }
    clauses = [
        SimpleNamespace(
            clause_type="bond",
            page_start=3,
            confidence_score=0.91,
            clause_text="Employee must pay INR 150000 if they leave before 18 months.",
        ),
        SimpleNamespace(
            clause_type="payment",
            page_start=2,
            confidence_score=0.88,
            clause_text="Salary is payable monthly by the 5th day of each month.",
        ),
    ]
    findings = [SimpleNamespace(confidence_score=0.86)]

    payload = service._build_payload(document=document, analysis=analysis, clauses=clauses, findings=findings)
    markdown = service._render_markdown(payload)

    assert payload["analysis"]["overall_risk_level"] == "high"
    assert payload["questions_to_ask"]
    assert "termination" in payload["analysis"]["missing_clauses"]
    assert "ClauseGuide AI Risk Report" in markdown
    assert "Top Risky Clauses" in markdown
    assert "Questions to Ask Before Signing" in markdown
