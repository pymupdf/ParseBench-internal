"""Provider for PyMuPDF4LLM PARSE."""

import html
import importlib
import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

from parse_bench.inference.providers.base import (
    Provider,
    ProviderConfigError,
    ProviderPermanentError,
)
from parse_bench.inference.providers.registry import register_provider
from parse_bench.schemas.parse_output import (
    LayoutItemIR,
    LayoutSegmentIR,
    PageIR,
    ParseLayoutPageIR,
    ParseOutput,
)
from parse_bench.schemas.pipeline import PipelineSpec
from parse_bench.schemas.pipeline_io import (
    InferenceRequest,
    InferenceResult,
    RawInferenceResult,
)
from parse_bench.schemas.product import ProductType

logger = logging.getLogger(__name__)

# A CommonMark parser with the GFM table rule enabled. Reused across calls.
_MD = MarkdownIt("commonmark").enable("table")


def _is_pipe_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _is_separator_row(line: str) -> bool:
    stripped = line.strip().strip("|")
    if not stripped:
        return False
    cells = [cell.strip() for cell in stripped.split("|")]
    return all(cell and re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _split_pipe_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _render_cell_inline(cell: str) -> str:
    # Malformed OCR pipe splits can break a bold span across cells:
    # ``**EFT||Tenure**`` becomes ``**EFT`` and ``Tenure**``.
    if cell.startswith("**") and not cell.endswith("**"):
        cell = cell[2:]
    if cell.endswith("**") and not cell.startswith("**"):
        cell = cell[:-2]
    rendered = _MD.renderInline(cell).strip()
    return rendered if rendered else html.escape(cell)


def _render_html_table(rows: list[list[str]], *, header_rows: int = 1) -> str:
    if not rows:
        return ""

    max_cols = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (max_cols - len(row)) for row in rows]
    parts = ["<table>"]

    if header_rows > 0:
        parts.append("<thead>")
        for row in normalized_rows[:header_rows]:
            cells = "".join(f"<th>{_render_cell_inline(cell)}</th>" for cell in row)
            parts.append(f"<tr>{cells}</tr>")
        parts.append("</thead>")

    body_rows = normalized_rows[header_rows:]
    if body_rows:
        parts.append("<tbody>")
        for row in body_rows:
            cells = "".join(f"<td>{_render_cell_inline(cell)}</td>" for cell in row)
            parts.append(f"<tr>{cells}</tr>")
        parts.append("</tbody>")

    parts.append("</table>")
    return "\n".join(parts)


def _render_forgiving_pipe_table(block: list[str]) -> str | None:
    if len(block) < 2:
        return None

    separator_idx = next((idx for idx, line in enumerate(block) if _is_separator_row(line)), None)
    if separator_idx is None:
        return None

    rows = [_split_pipe_row(line) for idx, line in enumerate(block) if idx != separator_idx]
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        return None

    max_cols = max(len(row) for row in rows)
    if max_cols < 2:
        return None

    return _render_html_table(rows, header_rows=max(separator_idx, 1))


def _render_strict_pipe_tables(text: str) -> str:
    tokens = _MD.parse(text)
    lines = text.split("\n")

    # Collect (start_line, end_line_exclusive, rendered_html) for each table.
    spans: list[tuple[int, int, str]] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.type == "table_open" and tok.map:
            start, end = tok.map
            j = i
            while j < n and tokens[j].type != "table_close":
                j += 1
            html_text = _MD.renderer.render(tokens[i : j + 1], _MD.options, {})
            spans.append((start, end, html_text.rstrip("\n")))
            i = j + 1
        else:
            i += 1

    for start, end, html_text in sorted(spans, reverse=True):
        lines[start:end] = [html_text]
    return "\n".join(lines)


def _render_forgiving_pipe_tables(text: str) -> str:
    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        if not _is_pipe_table_line(lines[i]):
            result.append(lines[i])
            i += 1
            continue

        start = i
        while i < len(lines) and _is_pipe_table_line(lines[i]):
            i += 1
        block = lines[start:i]

        if any("<table" in line.lower() for line in block):
            result.extend(block)
            continue

        rendered = _render_forgiving_pipe_table(block)
        if rendered is None:
            result.extend(block)
        else:
            result.append(rendered)

    return "\n".join(result)


def _table_from_time_rows(lines: list[str], start: int) -> tuple[str, int] | None:
    segments = [segment.strip() for segment in re.split(r"<br\s*/?>", lines[start], flags=re.IGNORECASE)]
    title = segments[0].strip()
    if " to " not in title.lower() or "|" in title or "<table" in title.lower():
        return None

    rows: list[list[str]] = []
    has_inline_rows = len(segments) > 1
    for segment in segments[1:]:
        cells = re.findall(r"\b\d{1,2}:\d{2}\b", segment)
        if len(cells) < 2:
            break
        rows.append(cells)

    i = start + 1
    while not has_inline_rows and i < len(lines):
        line = lines[i].strip()
        if not line:
            if rows:
                break
            i += 1
            continue
        if "|" in line or "<table" in line.lower():
            break
        cells = re.findall(r"\b\d{1,2}:\d{2}\b", line)
        if len(cells) < 2:
            break
        rows.append(cells)
        i += 1

    if len(rows) < 3:
        return None

    max_cols = max(len(row) for row in rows)
    if max_cols < 2:
        return None
    title_row = [title, *[""] * (max_cols - 1)]
    column_row = [f"Column {idx}" for idx in range(1, max_cols + 1)]
    return _render_html_table([title_row, column_row, *rows], header_rows=2), i


def _table_from_rate_line(line: str) -> str | None:
    stripped = line.strip()
    match = re.match(r"^(?:#+\s*)?\*\*Rate\*\*(?:\s|:|$)(.*)$", stripped)
    if match is None:
        return None
    remainder = match.group(1).strip(" :")
    if not remainder:
        return None
    amount_match = re.search(r"(\$[\d,]+(?:\.\d+)?)\s*$", remainder)
    if amount_match is None:
        return None
    description = remainder[: amount_match.start()].strip(" :-")
    amount = amount_match.group(1)
    if not description:
        return None
    return _render_html_table([["Rate"], [amount]], header_rows=1)


def recover_simple_tables(text: str) -> str:
    """Recover narrow PyMuPDF table misses that contain no usable pipe table."""
    if "<table" in text.lower():
        return text

    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        rate_table = _table_from_rate_line(lines[i])
        if rate_table is not None:
            result.append(lines[i])
            result.append("")
            result.append(rate_table)
            i += 1
            continue

        time_table = _table_from_time_rows(lines, i)
        if time_table is not None:
            table_html, next_i = time_table
            result.extend(lines[i:next_i])
            result.append("")
            result.append(table_html)
            i = next_i
            continue

        result.append(lines[i])
        i += 1

    return "\n".join(result)


def convert_pipe_tables_to_html(text: str) -> str:
    """Replace GFM pipe tables in *text* with equivalent HTML ``<table>`` blocks.

    Uses ``markdown-it-py`` to locate every GFM table and render it to HTML. Each
    table's source-line span (the ``table_open`` token's ``.map``) is replaced
    in-place with the rendered ``<table>`` markup; everything else is preserved
    byte-for-byte. Replacements are applied bottom-up so earlier line indices
    stay valid.

    Well-formed GFM tables are converted first. Remaining obvious PyMuPDF table
    blocks are converted with a forgiving row splitter because OCR sometimes
    emits extra literal pipes inside cell text (for example ``N||00-06M``),
    which makes the table invisible to the benchmark's HTML-table metrics.
    """
    converted = _render_strict_pipe_tables(text) if "|" in text else text
    converted = _render_forgiving_pipe_tables(converted) if "|" in converted else converted
    return recover_simple_tables(converted)


# PyMuPDF Layout 1.28 emits exactly the DocLayNet/Core11 classes. Keep the
# mapping strict so a new upstream class does not silently become incorrect
# benchmark ground truth.
_PYMUPDF_CLASS_TO_CANONICAL = {
    "caption": "Caption",
    "footnote": "Footnote",
    "formula": "Formula",
    "list-item": "List-item",
    "page-footer": "Page-footer",
    "page-header": "Page-header",
    "picture": "Picture",
    "section-header": "Section-header",
    "table": "Table",
    "text": "Text",
    "title": "Title",
}


@register_provider("pymupdf4llm")
class PyMuPDF4LLMProvider(Provider):
    """Provider for PyMuPDF4LLM (markdown). AGPL — runtime dep only."""

    def __init__(self, provider_name: str, base_config: dict[str, Any] | None = None):
        super().__init__(provider_name, base_config)

    def _markdown_options(self, pymupdf: Any) -> dict[str, Any]:
        options: dict[str, Any] = {
            "page_chunks": True,
            "show_progress": False,
        }

        use_ocr = self.base_config.get("use_ocr")
        if use_ocr is not None:
            if not isinstance(use_ocr, bool):
                raise ProviderConfigError("PyMuPDF4LLM 'use_ocr' must be a boolean")
            options["use_ocr"] = use_ocr

        force_ocr = self.base_config.get("force_ocr")
        if force_ocr is not None:
            if not isinstance(force_ocr, bool):
                raise ProviderConfigError("PyMuPDF4LLM 'force_ocr' must be a boolean")
            options["force_ocr"] = force_ocr

        if use_ocr is False and force_ocr is True:
            raise ProviderConfigError("PyMuPDF4LLM cannot set force_ocr=True when use_ocr=False")

        ocr_dpi = self.base_config.get("ocr_dpi")
        if ocr_dpi is not None:
            if isinstance(ocr_dpi, bool) or not isinstance(ocr_dpi, int) or ocr_dpi <= 0:
                raise ProviderConfigError("PyMuPDF4LLM 'ocr_dpi' must be a positive integer")
            options["ocr_dpi"] = ocr_dpi

        ocr_language = self.base_config.get("ocr_language")
        if ocr_language is not None:
            if not isinstance(ocr_language, str) or not ocr_language.strip():
                raise ProviderConfigError("PyMuPDF4LLM 'ocr_language' must be a non-empty string")
            options["ocr_language"] = ocr_language

        raw_backend = self.base_config.get("ocr_backend")
        if raw_backend is None:
            return options
        if not isinstance(raw_backend, str):
            raise ProviderConfigError("PyMuPDF4LLM 'ocr_backend' must be a string")

        backend = raw_backend.strip().lower()
        if backend == "auto":
            return options

        backend_modules = {
            "rapidocr": "pymupdf4llm.ocr.rapidocr_api",
            "tesseract": "pymupdf4llm.ocr.tesseract_api",
        }
        module_name = backend_modules.get(backend)
        if module_name is None:
            supported = ", ".join(["auto", *backend_modules])
            raise ProviderConfigError(
                f"Unsupported PyMuPDF4LLM OCR backend '{raw_backend}'. Supported backends: {supported}"
            )

        if backend == "tesseract" and pymupdf.get_tessdata() is None:
            raise ProviderConfigError("PyMuPDF4LLM Tesseract backend requires Tesseract language data")

        try:
            ocr_module = importlib.import_module(module_name)
        except (ImportError, RuntimeError) as e:
            raise ProviderConfigError(f"PyMuPDF4LLM OCR backend '{backend}' is unavailable: {e}") from e

        ocr_function = getattr(ocr_module, "exec_ocr", None)
        if not callable(ocr_function):
            raise ProviderConfigError(f"PyMuPDF4LLM OCR backend '{backend}' does not expose exec_ocr")
        options["ocr_function"] = ocr_function
        return options

    def _extract(self, pdf_path: str) -> dict[str, Any]:
        try:
            import pymupdf
            import pymupdf4llm  # type: ignore[import-untyped]
        except ImportError as e:
            raise ProviderConfigError("pymupdf4llm not installed. Run: pip install pymupdf4llm") from e

        try:
            markdown_options = self._markdown_options(pymupdf)
            page_chunks = pymupdf4llm.to_markdown(pdf_path, **markdown_options)
            with pymupdf.open(pdf_path) as document:
                page_dimensions = [(float(page.rect.width), float(page.rect.height)) for page in document]
        except ProviderConfigError:
            raise
        except Exception as e:
            raise ProviderPermanentError(f"PyMuPDF4LLM error: {e}") from e

        pages = []
        for i, chunk in enumerate(page_chunks):
            text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
            metadata = chunk.get("metadata", {}) if isinstance(chunk, dict) else {}
            raw_page_number = metadata.get("page_number") if isinstance(metadata, dict) else None
            if isinstance(raw_page_number, (int, float, str)):
                try:
                    page_number = int(raw_page_number)
                except ValueError:
                    page_number = i + 1
            else:
                page_number = i + 1

            dimension_index = page_number - 1
            if not 0 <= dimension_index < len(page_dimensions):
                dimension_index = i
            if 0 <= dimension_index < len(page_dimensions):
                width, height = page_dimensions[dimension_index]
            else:
                width, height = 0.0, 0.0

            page_boxes = chunk.get("page_boxes", []) if isinstance(chunk, dict) else []
            if not isinstance(page_boxes, list):
                page_boxes = []

            pages.append(
                {
                    "page_index": i,
                    "page_number": page_number,
                    "text": text,
                    "width": width,
                    "height": height,
                    "page_boxes": page_boxes,
                }
            )

        return {"pages": pages, "num_pages": len(pages)}

    def run_inference(self, pipeline: PipelineSpec, request: InferenceRequest) -> RawInferenceResult:
        if request.product_type != ProductType.PARSE:
            raise ProviderPermanentError(f"PyMuPDF4LLMProvider only supports PARSE, got {request.product_type}")

        pdf_path = Path(request.source_file_path)
        if not pdf_path.exists():
            raise ProviderPermanentError(f"File not found: {pdf_path}")

        started_at = datetime.now()
        try:
            raw_output = self._extract(str(pdf_path))
            completed_at = datetime.now()
            return RawInferenceResult(
                request=request,
                pipeline=pipeline,
                pipeline_name=pipeline.pipeline_name,
                product_type=request.product_type,
                raw_output=raw_output,
                started_at=started_at,
                completed_at=completed_at,
                latency_in_ms=int((completed_at - started_at).total_seconds() * 1000),
            )
        except (ProviderPermanentError, ProviderConfigError):
            raise
        except Exception as e:
            raise ProviderPermanentError(f"Unexpected error: {e}") from e

    @staticmethod
    def _convert_md_tables_to_html(content: str) -> str:
        return convert_pipe_tables_to_html(content)

    @staticmethod
    def _coerce_bbox(
        raw_bbox: Any,
        *,
        page_width: float,
        page_height: float,
    ) -> tuple[float, float, float, float] | None:
        """Validate, clamp, and normalize a PyMuPDF XYXY bbox to XYWH."""
        if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
            return None
        try:
            x0, y0, x1, y1 = (float(value) for value in raw_bbox)
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
            return None
        if page_width <= 0 or page_height <= 0:
            return None

        x0 = min(max(x0, 0.0), page_width)
        x1 = min(max(x1, 0.0), page_width)
        y0 = min(max(y0, 0.0), page_height)
        y1 = min(max(y1, 0.0), page_height)
        if x1 <= x0 or y1 <= y0:
            return None
        return (
            x0 / page_width,
            y0 / page_height,
            (x1 - x0) / page_width,
            (y1 - y0) / page_height,
        )

    @staticmethod
    def _coerce_text_range(raw_pos: Any, text_length: int) -> tuple[int, int] | None:
        """Validate and clamp a page-box Markdown character range."""
        if not isinstance(raw_pos, (list, tuple)) or len(raw_pos) != 2:
            return None
        start, stop = raw_pos
        if isinstance(start, bool) or isinstance(stop, bool):
            return None
        try:
            start = int(start)
            stop = int(stop)
        except (TypeError, ValueError):
            return None
        start = min(max(start, 0), text_length)
        stop = min(max(stop, 0), text_length)
        if stop < start:
            return None
        return start, stop

    @classmethod
    def _build_layout_page(
        cls,
        page_data: dict[str, Any],
        *,
        raw_markdown: str,
    ) -> ParseLayoutPageIR | None:
        """Convert PyMuPDF page boxes into benchmark visual-grounding IR."""
        try:
            page_number = int(page_data.get("page_number", 0))
            page_width = float(page_data.get("width", 0.0))
            page_height = float(page_data.get("height", 0.0))
        except (TypeError, ValueError):
            return None
        if page_number < 1 or page_width <= 0 or page_height <= 0:
            return None

        items: list[LayoutItemIR] = []
        unknown_classes: set[str] = set()
        for page_box in page_data.get("page_boxes", []):
            if not isinstance(page_box, dict):
                continue

            raw_class = str(page_box.get("class", "")).strip().lower().replace("_", "-")
            canonical_label = _PYMUPDF_CLASS_TO_CANONICAL.get(raw_class)
            if canonical_label is None:
                if raw_class:
                    unknown_classes.add(raw_class)
                continue

            bbox = cls._coerce_bbox(
                page_box.get("bbox"),
                page_width=page_width,
                page_height=page_height,
            )
            if bbox is None:
                continue

            text_range = cls._coerce_text_range(page_box.get("pos"), len(raw_markdown))
            if text_range is None:
                start_index = None
                end_index = None
                content = ""
            else:
                start_index, end_index = text_range
                content = raw_markdown[start_index:end_index]

            raw_confidence = page_box.get("confidence")
            confidence: float | None = None
            if raw_confidence is not None:
                try:
                    parsed_confidence = float(raw_confidence)
                except (TypeError, ValueError):
                    parsed_confidence = math.nan
                if math.isfinite(parsed_confidence) and 0.0 <= parsed_confidence <= 1.0:
                    confidence = parsed_confidence

            segment = LayoutSegmentIR(
                x=bbox[0],
                y=bbox[1],
                w=bbox[2],
                h=bbox[3],
                confidence=confidence,
                label=canonical_label,
                start_index=start_index,
                end_index=end_index,
            )

            if canonical_label == "Table":
                item_type = "table"
                item_html = cls._convert_md_tables_to_html(content)
            elif canonical_label == "Picture":
                item_type = "image"
                item_html = ""
            else:
                # Field-grounding evaluation consumes text-like items while the
                # canonical category remains on the segment label.
                item_type = "text"
                item_html = ""

            items.append(
                LayoutItemIR(
                    type=item_type,
                    md=content,
                    html=item_html,
                    value=content,
                    bbox=segment,
                    layout_segments=[segment],
                )
            )

        if unknown_classes:
            logger.warning(
                "Skipping unknown PyMuPDF4LLM layout classes on page %s: %s",
                page_number,
                ", ".join(sorted(unknown_classes)),
            )

        return ParseLayoutPageIR(
            page_number=page_number,
            width=page_width,
            height=page_height,
            md=raw_markdown,
            text=raw_markdown,
            items=items,
        )

    def normalize(self, raw_result: RawInferenceResult) -> InferenceResult:
        pages: list[PageIR] = []
        layout_pages: list[ParseLayoutPageIR] = []
        page_texts: list[str] = []
        for page_data in raw_result.raw_output.get("pages", []):
            page_index = page_data.get("page_index", 0)
            raw_markdown = page_data.get("text", "") or ""
            layout_page = self._build_layout_page(page_data, raw_markdown=raw_markdown)
            if layout_page is not None:
                layout_pages.append(layout_page)

            # page_boxes[*].pos refers to raw_markdown. Build layout items
            # before this table conversion changes character offsets.
            text = self._convert_md_tables_to_html(raw_markdown)
            pages.append(PageIR(page_index=page_index, markdown=text))
            page_texts.append(text)

        full_text = "\n\n".join(page_texts)
        output = ParseOutput(
            task_type="parse",
            example_id=raw_result.request.example_id,
            pipeline_name=raw_result.pipeline_name,
            pages=pages,
            layout_pages=layout_pages,
            markdown=full_text,
        )
        return InferenceResult(
            request=raw_result.request,
            pipeline_name=raw_result.pipeline_name,
            product_type=raw_result.product_type,
            raw_output=raw_result.raw_output,
            output=output,
            started_at=raw_result.started_at,
            completed_at=raw_result.completed_at,
            latency_in_ms=raw_result.latency_in_ms,
        )
