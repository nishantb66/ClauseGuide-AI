from app.services.legal_kb_service import get_legal_kb
from app.services.risk_engine import ClauseRiskInput, RiskEngine


def test_legal_kb_loads_document_playbook_and_rules() -> None:
    kb = get_legal_kb()

    playbook = kb.playbook("government_empanelment")
    metadata = kb.cuad_metadata()

    assert playbook["display_name"] == "Government / Empanelment / Tender Agreement"
    assert "termination" in kb.expected_clauses("government_empanelment")
    assert kb.risk_rules_for("government_empanelment", "compliance")
    assert metadata["contract_count"] == 510
    assert metadata["cuad_label_count"] == 41
    assert metadata["positive_answer_count"] >= 13000
    assert kb.cuad_labels_for("liability")
    assert "unlimited liability" in kb.aliases_for("liability")


def test_kb_rule_flags_blacklisting_due_process_risk() -> None:
    engine = RiskEngine()
    clause = ClauseRiskInput(
        id=1,
        clause_type="compliance",
        clause_title="Compliance and Debarment",
        clause_text=(
            "The Authority may blacklist or debar the vendor at its sole discretion "
            "for non-compliance with applicable policies."
        ),
        normalized_text=(
            "the authority may blacklist or debar the vendor at its sole discretion "
            "for non-compliance with applicable policies"
        ),
        page_start=4,
    )

    result = engine.analyze("government_empanelment", [clause])

    assert any(
        finding.risk_category == "compliance_playbook_risk"
        and "Blacklisting" in finding.summary
        and finding.risk_level in {"high", "critical"}
        for finding in result.findings
    )
