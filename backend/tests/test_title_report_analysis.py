from app.services.document_classifier import DocumentClassifier
from app.services.placeholder_detector import PlaceholderDetector
from app.services.text_cleaner import CleanedPage
from app.services.title_report_analyzer import TitleReportAnalyzer


def page(number: int, text: str) -> CleanedPage:
    return CleanedPage(page_number=number, raw_text=text, cleaned_text=text)


def test_title_report_uses_property_review_instead_of_contract_checklist() -> None:
    pages = [
        page(1, "LEGAL TITLE REPORT\nTitle clearance report for Plot RZ-02, Gat No. 24/1/2.\n"
             "I investigated the title on request of Persipina Developers Pvt. Ltd.\n"
             "________________________________________________________________________"),
        page(8, "The secured creditor sold the property on an as is where is basis "
             "together with encumbrances and litigations mentioned in the sale certificate."),
        page(13, "The title is clear, marketable save and except the encumbrances and "
             "pending litigation in Annexure B. Litigation: R.C.S. No. 333/15 is a civil "
             "suit about encroachment. No adverse order has been passed as of this report."),
        page(39, "Title appears good subject to compliance and removal of encumbrances "
             "and to comply with the terms of the master layout approval."),
        page(40, "ANNEXURE B ENCUMBRANCES. The developer has mortgaged the land for "
             "project finance. The project assets stand hypothecated and charged to a trustee."),
    ]

    classification = DocumentClassifier().classify(pages)
    result = TitleReportAnalyzer().analyze(pages)

    assert classification.primary_document_type == "legal_title_report"
    assert not classification.is_template
    assert not classification.contains_multiple_document_types
    assert [finding.page_number for finding in result.findings] == [40, 13, 13, 8, 39]
    assert {finding.risk_category for finding in result.findings} == {
        "project_finance_charge_risk", "qualified_title_opinion_risk",
        "pending_litigation_risk", "auction_encumbrance_risk",
        "approval_conditions_risk",
    }
    assert all("payment" not in finding.risk_category for finding in result.findings)
    assert result.overall_risk_level == "high"
    assert not PlaceholderDetector().detect_pages([(1, pages[0].cleaned_text)])


def test_historical_mortgage_alone_is_not_called_a_current_charge() -> None:
    result = TitleReportAnalyzer().analyze([
        page(1, "LEGAL TITLE REPORT for the identified property."),
        page(2, "A mortgage deed dated 2010 was executed in favour of a bank and a sale "
             "certificate was issued in 2014."),
    ])

    assert result.findings == []


def test_loan_that_cites_an_attached_title_report_remains_a_loan() -> None:
    classification = DocumentClassifier().classify([
        page(1, "LOAN AGREEMENT\nThe borrower grants security over the property. "
             "A legal title report is attached as evidence. The lender may recover the loan."),
    ])

    assert classification.primary_document_type != "legal_title_report"
