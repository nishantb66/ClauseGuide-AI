from app.services.risk_engine import ClauseRiskInput, RiskEngine


def test_risk_engine_flags_bond_and_missing_clauses() -> None:
    engine = RiskEngine()

    clauses = [
        ClauseRiskInput(
            id=1,
            clause_type="bond",
            clause_title="Service Bond",
            clause_text="Employee must pay Rs 150000 if leaving before 18 months. Training cost mentioned.",
            normalized_text=(
                "employee must pay rs 150000 if leaving before 18 months training cost mentioned"
            ),
            page_start=3,
        ),
        ClauseRiskInput(
            id=2,
            clause_type="non_compete",
            clause_title="Non-Compete",
            clause_text=(
                "Employee shall not work with any competitor worldwide in any capacity for 12 months."
            ),
            normalized_text=(
                "employee shall not work with any competitor worldwide in any capacity for 12 months"
            ),
            page_start=4,
        ),
    ]

    result = engine.analyze("employment_bond", clauses)

    assert result.findings
    assert result.overall_risk_score >= 50
    assert result.overall_risk_level in {"high", "critical"}
    assert "termination" in result.missing_clauses
    assert any(finding.risk_category == "financial_risk" for finding in result.findings)


def test_risk_engine_uses_document_specific_missing_clause_severity() -> None:
    engine = RiskEngine()
    clauses = [
        ClauseRiskInput(
            id=1,
            clause_type="scope_of_services",
            clause_title="Scope",
            clause_text="The empanelled vendor shall provide services against work orders.",
            normalized_text="the empanelled vendor shall provide services against work orders",
            page_start=1,
        ),
        ClauseRiskInput(
            id=2,
            clause_type="payment",
            clause_title="Fee Schedule",
            clause_text="Payment shall be made according to the fee schedule after approval.",
            normalized_text="payment shall be made according to the fee schedule after approval",
            page_start=2,
        ),
    ]

    result = engine.analyze("government_empanelment", clauses)

    assert "payment" not in result.missing_clauses
    termination_gap = next(
        finding for finding in result.findings if "termination" in finding.summary.lower()
    )
    assert termination_gap.risk_level == "high"
    assert termination_gap.risk_score >= 60


def test_risk_engine_treats_recommended_gaps_as_optional() -> None:
    engine = RiskEngine()
    clauses = [
        ClauseRiskInput(
            id=1,
            clause_type="payment",
            clause_title="Rent",
            clause_text="The tenant shall pay monthly rent and a refundable security deposit.",
            normalized_text="the tenant shall pay monthly rent and a refundable security deposit",
            page_start=1,
        ),
        ClauseRiskInput(
            id=2,
            clause_type="termination",
            clause_title="Termination",
            clause_text="Either party may terminate after written notice.",
            normalized_text="either party may terminate after written notice",
            page_start=2,
        ),
        ClauseRiskInput(
            id=3,
            clause_type="maintenance",
            clause_title="Maintenance",
            clause_text="The owner shall handle structural repairs and tenant shall pay utilities.",
            normalized_text="the owner shall handle structural repairs and tenant shall pay utilities",
            page_start=2,
        ),
        ClauseRiskInput(
            id=4,
            clause_type="use_restrictions",
            clause_title="Use",
            clause_text="The premises shall only be used for residential purposes.",
            normalized_text="the premises shall only be used for residential purposes",
            page_start=3,
        ),
    ]

    result = engine.analyze("rental_agreement", clauses)

    assert "payment" not in result.missing_clauses
    assert all(
        finding.risk_score < 20
        for finding in result.findings
        if finding.risk_category == "recommended_review_gap"
    )
