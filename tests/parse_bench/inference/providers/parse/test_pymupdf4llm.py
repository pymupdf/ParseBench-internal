"""Tests for PyMuPDF4LLM layout normalization helpers."""

from parse_bench.inference.providers.parse.pymupdf4llm import PyMuPDF4LLMProvider


def _build_page(page_boxes: list[dict], *, raw_markdown: str):
    return PyMuPDF4LLMProvider._build_layout_page(
        {
            "page_number": 1,
            "width": 100,
            "height": 100,
            "page_boxes": page_boxes,
        },
        raw_markdown=raw_markdown,
    )


def test_build_layout_page_emits_raw_boxclass_labels() -> None:
    """Provider forwards raw boxclass labels verbatim and never drops unknowns.

    Canonicalization (and failing loud on unknown classes) is owned by the
    evaluation label-mapper layer, so an unrecognized class must survive here.
    """
    markdown = "grounded content"
    raw_classes = [
        "caption",
        "table",
        "section-header",
        "text",
        "picture",
        "totally-unknown-class",
    ]
    page_boxes = [
        {
            "class": raw_class,
            "bbox": [10, 10 + index * 5, 90, 14 + index * 5],
            "pos": [0, len(markdown)],
        }
        for index, raw_class in enumerate(raw_classes)
    ]

    page = _build_page(page_boxes, raw_markdown=markdown)

    assert page is not None
    assert [item.layout_segments[0].label for item in page.items] == raw_classes


def test_build_layout_page_sets_item_type_from_raw_class() -> None:
    markdown = "x"
    page_boxes = [
        {"class": "Table", "bbox": [10, 10, 90, 20], "pos": [0, 1]},
        {"class": "picture", "bbox": [10, 25, 90, 40], "pos": [0, 1]},
        {"class": "section_header", "bbox": [10, 45, 90, 60], "pos": [0, 1]},
    ]

    page = _build_page(page_boxes, raw_markdown=markdown)

    assert page is not None
    assert [item.type for item in page.items] == ["table", "image", "text"]


def test_table_native_html_content_is_passed_through() -> None:
    """A native <table> in the sliced content is preserved untouched."""
    markdown = "<table><tr><td>a</td><td>b</td></tr></table>"
    page_boxes = [{"class": "table", "bbox": [10, 10, 90, 90], "pos": [0, len(markdown)]}]

    page = _build_page(page_boxes, raw_markdown=markdown)

    assert page is not None
    item = page.items[0]
    assert item.type == "table"
    assert item.html == markdown


def test_table_pipe_markdown_is_converted_to_html() -> None:
    """Markdown pipe tables still fall back to the markdown2 conversion."""
    markdown = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    page_boxes = [{"class": "table", "bbox": [10, 10, 90, 90], "pos": [0, len(markdown)]}]

    page = _build_page(page_boxes, raw_markdown=markdown)

    assert page is not None
    item = page.items[0]
    assert item.type == "table"
    assert item.html != markdown
    assert "<table>" in item.html.lower()
