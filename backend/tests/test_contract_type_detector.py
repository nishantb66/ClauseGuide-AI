from app.services.contract_type_detector import ContractTypeDetector


def test_detects_employment_bond() -> None:
    detector = ContractTypeDetector()
    text = (
        "This employment agreement includes a service bond. "
        "The employee shall pay liquidated damages if they leave before the bond period ends."
    )

    result = detector.detect(text)

    assert result.contract_type == "employment_bond"
    assert result.confidence_score > 0.2


def test_detects_rental_agreement() -> None:
    detector = ContractTypeDetector()
    text = (
        "This lease is entered between landlord and tenant. "
        "The tenant shall pay monthly rent and security deposit."
    )

    result = detector.detect(text)

    assert result.contract_type == "rental_agreement"


def test_detects_government_empanelment_over_generic_freelance() -> None:
    detector = ContractTypeDetector()
    text = (
        "Request for proposal for empanelment of consultants by the Authority. "
        "The selected service provider may receive work orders as and when required. "
        "Poor performance may lead to blacklisting or debarment. The client may issue no guaranteed work."
    )

    result = detector.detect(text)

    assert result.contract_type == "government_empanelment"
    assert "empanelment" in result.evidence_keywords


def test_detects_software_saas_agreement() -> None:
    detector = ContractTypeDetector()
    text = (
        "This software subscription agreement grants a license to access the SaaS platform. "
        "The vendor provides uptime commitments, data protection, subprocessor terms, and data deletion."
    )

    result = detector.detect(text)

    assert result.contract_type == "software_saas_agreement"
