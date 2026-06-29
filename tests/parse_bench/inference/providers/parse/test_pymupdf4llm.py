"""Tests for PyMuPDF4LLM layout normalization helpers."""

from parse_bench.inference.providers.parse.pymupdf4llm import (
    _PYMUPDF_CLASS_TO_CANONICAL,
    PyMuPDF4LLMProvider,
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
