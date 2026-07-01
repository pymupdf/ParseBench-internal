"""Tests for PyMuPDF4LLM layout normalization helpers."""

from parse_bench.inference.providers.parse.pymupdf4llm import (
    _PYMUPDF_CLASS_TO_CANONICAL,
    PyMuPDF4LLMProvider,
    convert_pipe_tables_to_html,
)


def test_build_layout_page_maps_all_pymupdf_classes() -> None:
    markdown = "grounded content"
    page_boxes = [
        {
            "class": raw_class,
            "bbox": [10, 10 + index * 5, 90, 14 + index * 5],
            "pos": [0, len(markdown)],
        }
        for index, raw_class in enumerate(_PYMUPDF_CLASS_TO_CANONICAL)
    ]

    page = PyMuPDF4LLMProvider._build_layout_page(
        {
            "page_number": 1,
            "width": 100,
            "height": 100,
            "page_boxes": page_boxes,
        },
        raw_markdown=markdown,
    )

    assert page is not None
    assert [item.layout_segments[0].label for item in page.items] == list(_PYMUPDF_CLASS_TO_CANONICAL.values())


def test_convert_pipe_tables_to_html_handles_malformed_pymupdf_table() -> None:
    markdown = "\n".join(
        [
            "|**EFT||Tenure**|**Earned Car**|**Loss**|",
            "|---|---|---|",
            "|N||00-06M|108,985|54,948,344|",
            "|Y||00-06M|285,847|160,848,153|",
        ]
    )

    html = convert_pipe_tables_to_html(markdown)

    assert "<table>" in html
    assert "<th>EFT</th>" in html
    assert "<th>Tenure</th>" in html
    assert "<td>N</td>" in html
    assert "<td>00-06M</td>" in html


def test_convert_pipe_tables_to_html_recovers_simple_rate_table() -> None:
    markdown = "**Rate** Per Each Location/ Each Additional Insured $12.86"

    html = convert_pipe_tables_to_html(markdown)

    assert "<table>" in html
    assert "<th>Rate</th>" in html
    assert "<td>$12.86</td>" in html


def test_convert_pipe_tables_to_html_recovers_time_rows_from_picture_text() -> None:
    markdown = "\n".join(
        [
            "Sundays to Manhattan",
            "12:00 12:04 12:17",
            "12:09 12:13 12:26",
            "12:14 12:18 12:31",
        ]
    )

    html = convert_pipe_tables_to_html(markdown)

    assert "<table>" in html
    assert "<th>Sundays to Manhattan</th>" in html
    assert "<td>12:09</td>" in html


def test_convert_pipe_tables_to_html_does_not_recover_generic_rate_text() -> None:
    markdown = "The interest rate changed and the loss was $8,665,000."

    assert convert_pipe_tables_to_html(markdown) == markdown
