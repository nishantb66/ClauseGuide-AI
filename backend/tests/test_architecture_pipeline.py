from app.services.clause_normalizer import ClauseNormalizer
from app.services.document_classifier import DocumentClassifier
from app.services.placeholder_detector import PlaceholderDetector
from app.services.risk_engine import ClauseRiskInput, RiskEngine
from app.services.text_cleaner import CleanedPage


def test_auto_renewal_requires_positive_automatic_language() -> None:
    normalizer = ClauseNormalizer()

    weak_signal = normalizer.signal_for(
        "auto_renewal", "This agreement may be renewed by mutual consent."
    )
    strong_signal = normalizer.signal_for(
        "auto_renewal",
        "This agreement shall automatically renew for successive renewal terms unless either party gives notice.",
    )

    assert not weak_signal.exists
    assert strong_signal.exists


def test_risk_engine_drops_false_auto_renewal_risk() -> None:
    engine = RiskEngine()
    clause = ClauseRiskInput(
        id=1,
        clause_type="auto_renewal",
        clause_title="Renewal",
        clause_text="The facility may be renewed by mutual consent and subject to approval.",
        normalized_text="the facility may be renewed by mutual consent and subject to approval",
        page_start=2,
    )

    result = engine.analyze("loan_agreement", [clause])

    assert not any(finding.risk_category == "auto_renewal_risk" for finding in result.findings)


def test_document_classifier_detects_template_collection() -> None:
    classifier = DocumentClassifier()
    pages = [
        CleanedPage(
            page_number=1,
            raw_text="",
            cleaned_text=(
                "TABLE OF CONTENTS\n"
                "1. AGREEMENT FOR EDUCATIONAL LOAN\n"
                "2. GENERAL LEASE DEED\n"
                "3. GIFT DEED\n"
                "This is a template collection with blank fields ______."
            ),
        ),
        CleanedPage(
            page_number=2,
            raw_text="",
            cleaned_text="AGREEMENT FOR EDUCATIONAL LOAN\nBorrower shall repay the loan with interest.",
        ),
        CleanedPage(
            page_number=3,
            raw_text="",
            cleaned_text="GENERAL LEASE DEED\nThe tenant shall pay rent and security deposit.",
        ),
    ]

    result = classifier.classify(pages)

    assert result.primary_document_type == "legal_template_collection"
    assert result.is_template
    assert result.contains_multiple_document_types


def test_placeholder_detector_identifies_blank_amount_field() -> None:
    detector = PlaceholderDetector()

    issues = detector.detect_pages([(1, "The Borrower shall receive a loan of INR ____________.")])

    assert issues
    assert issues[0].field == "loan amount"
