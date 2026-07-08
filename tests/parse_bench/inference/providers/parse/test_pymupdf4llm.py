"""Tests for PyMuPDF4LLM provider helpers."""

import types

import pytest

import parse_bench.inference.providers.parse.pymupdf4llm as pymupdf4llm_module
from parse_bench.inference.providers.base import ProviderConfigError
from parse_bench.inference.providers.parse.pymupdf4llm import (
    _OCR_BACKEND_MODULES,
    PyMuPDF4LLMProvider,
)


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


def test_markdown_options_mirror_library_kwargs() -> None:
    """Config keys mirror pymupdf4llm.to_markdown and are forwarded verbatim."""
    provider = PyMuPDF4LLMProvider(
        "pymupdf4llm",
        {"use_ocr": True, "force_ocr": True, "ocr_dpi": 150, "ocr_language": "deu"},
    )
    options = provider._markdown_options()

    assert options == {
        "page_chunks": True,
        "show_progress": False,
        "use_ocr": True,
        "force_ocr": True,
        "ocr_dpi": 150,
        "ocr_language": "deu",
    }


def test_markdown_options_are_declarative_no_callable_injected() -> None:
    """The options dict must stay serializable: no ocr_function/ocr_backend keys."""
    provider = PyMuPDF4LLMProvider("pymupdf4llm", {"ocr_backend": "tesseract"})
    options = provider._markdown_options()

    assert "ocr_function" not in options
    assert "ocr_backend" not in options
    assert all(not callable(value) for value in options.values())


def test_markdown_options_does_not_probe_tessdata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: the proactive pymupdf.get_tessdata() probe is gone.

    Selecting the tesseract backend must not eagerly probe the OCR engine
    (the probe spawned a subprocess and cost ~350 ms/page). Building the
    declarative options must succeed even if get_tessdata would raise.
    """
    import pymupdf

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("get_tessdata must not be probed while building options")

    monkeypatch.setattr(pymupdf, "get_tessdata", _boom)

    provider = PyMuPDF4LLMProvider("pymupdf4llm", {"ocr_backend": "tesseract"})
    # Does not raise -> the probe was not invoked.
    assert provider._markdown_options() == {"page_chunks": True, "show_progress": False}


@pytest.mark.parametrize("bad_backend", [123, ["tesseract"], object()])
def test_markdown_options_rejects_non_string_backend(bad_backend: object) -> None:
    provider = PyMuPDF4LLMProvider("pymupdf4llm", {"ocr_backend": bad_backend})
    with pytest.raises(ProviderConfigError, match="must be a string"):
        provider._markdown_options()


def test_markdown_options_rejects_unsupported_backend() -> None:
    provider = PyMuPDF4LLMProvider("pymupdf4llm", {"ocr_backend": "nonesuch"})
    with pytest.raises(ProviderConfigError, match="Unsupported PyMuPDF4LLM OCR backend"):
        provider._markdown_options()


@pytest.mark.parametrize("config", [{}, {"ocr_backend": "auto"}, {"ocr_backend": "AUTO"}])
def test_resolve_ocr_function_defers_to_library(config: dict[str, object]) -> None:
    """Absent or 'auto' backend returns None so pymupdf4llm selects the engine."""
    provider = PyMuPDF4LLMProvider("pymupdf4llm", config)
    assert provider._resolve_ocr_function() is None


@pytest.mark.parametrize("backend", sorted(_OCR_BACKEND_MODULES))
def test_resolve_ocr_function_resolves_backend_internally(backend: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine callable is resolved from the module map at call time."""
    imported: list[str] = []

    def _sentinel_exec_ocr(*args: object, **kwargs: object) -> None:
        return None

    fake_module = types.SimpleNamespace(exec_ocr=_sentinel_exec_ocr)

    def _fake_import(name: str) -> object:
        imported.append(name)
        return fake_module

    monkeypatch.setattr(pymupdf4llm_module.importlib, "import_module", _fake_import)

    provider = PyMuPDF4LLMProvider("pymupdf4llm", {"ocr_backend": backend})
    resolved = provider._resolve_ocr_function()

    assert resolved is _sentinel_exec_ocr
    assert imported == [_OCR_BACKEND_MODULES[backend]]


def test_resolve_ocr_function_unavailable_backend_is_reactive() -> None:
    """An unavailable engine fails only at resolve time, not at config time.

    rapidocr_onnxruntime is not installed in the test environment, so importing
    the backend raises ImportError. Building the declarative options must still
    succeed; the failure surfaces reactively from _resolve_ocr_function.
    """
    provider = PyMuPDF4LLMProvider("pymupdf4llm", {"ocr_backend": "rapidocr"})

    # Config/options stage stays clean.
    assert provider._markdown_options() == {"page_chunks": True, "show_progress": False}

    # Resolution stage raises reactively.
    with pytest.raises(ProviderConfigError, match="rapidocr.*unavailable"):
        provider._resolve_ocr_function()


def test_resolve_ocr_function_missing_exec_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    """A backend module without exec_ocr is a config error."""
    monkeypatch.setattr(
        pymupdf4llm_module.importlib,
        "import_module",
        lambda name: types.SimpleNamespace(),
    )
    provider = PyMuPDF4LLMProvider("pymupdf4llm", {"ocr_backend": "tesseract"})
    with pytest.raises(ProviderConfigError, match="does not expose exec_ocr"):
        provider._resolve_ocr_function()


def test_resolve_ocr_function_tesseract_without_tessdata_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicitly requested tesseract backend must not silently skip OCR.

    pymupdf4llm's tesseract_api imports cleanly when Tesseract is missing (it
    warns and its exec_ocr becomes a per-page no-op), so the ImportError guard
    never fires. The provider must read the module's TESSDATA marker and raise
    instead of letting the run quietly score without OCR.
    """
    fake_module = types.SimpleNamespace(exec_ocr=lambda *a, **k: None, TESSDATA=None)
    monkeypatch.setattr(pymupdf4llm_module.importlib, "import_module", lambda name: fake_module)

    provider = PyMuPDF4LLMProvider("pymupdf4llm", {"ocr_backend": "tesseract"})
    with pytest.raises(ProviderConfigError, match="Tesseract language data"):
        provider._resolve_ocr_function()


def test_resolve_ocr_function_tesseract_with_tessdata_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    """With Tesseract available (TESSDATA set), resolution succeeds."""

    def _sentinel_exec_ocr(*args: object, **kwargs: object) -> None:
        return None

    fake_module = types.SimpleNamespace(exec_ocr=_sentinel_exec_ocr, TESSDATA="/usr/share/tessdata")
    monkeypatch.setattr(pymupdf4llm_module.importlib, "import_module", lambda name: fake_module)

    provider = PyMuPDF4LLMProvider("pymupdf4llm", {"ocr_backend": "tesseract"})
    assert provider._resolve_ocr_function() is _sentinel_exec_ocr
