from app.services.document_parser import ExtractedPage
from app.services.text_cleaner import TextCleaner


def test_cleaner_removes_repeated_header_footer() -> None:
    cleaner = TextCleaner()
    pages = [
        ExtractedPage(page_number=1, text="ACME CONTRACT\nContent A\nConfidential"),
        ExtractedPage(page_number=2, text="ACME CONTRACT\nContent B\nConfidential"),
        ExtractedPage(page_number=3, text="ACME CONTRACT\nContent C\nConfidential"),
    ]

    result = cleaner.clean_pages(pages)

    assert result[0].cleaned_text == "Content A"
    assert result[1].cleaned_text == "Content B"
    assert result[2].cleaned_text == "Content C"
