"""Provider for PyMuPDF4LLM PARSE."""

import importlib
import logging
import math
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

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


# `ocr_backend` is a ParseBench-level config key (not a pymupdf4llm.to_markdown
# kwarg): it names which bundled OCR engine should back `ocr_function`. The
# engine callable is resolved from this map internally at call time (see
# `_resolve_ocr_function`) so it never enters a serialized options/config dict.
_OCR_BACKEND_MODULES = {
    "rapidocr": "pymupdf4llm.ocr.rapidocr_api",
    "tesseract": "pymupdf4llm.ocr.tesseract_api",
}


@register_provider("pymupdf4llm")
class PyMuPDF4LLMProvider(Provider):
    """Provider for PyMuPDF4LLM (markdown). AGPL — runtime dep only."""

    def __init__(self, provider_name: str, base_config: dict[str, Any] | None = None):
        super().__init__(provider_name, base_config)

    def _markdown_options(self) -> dict[str, Any]:
        # `use_ocr`, `force_ocr`, `ocr_dpi`, and `ocr_language` intentionally
        # mirror pymupdf4llm.to_markdown's kwargs 1:1 and are forwarded verbatim
        # below; keep these config keys aligned with the library API rather than
        # renaming them to match other providers.
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

        table_output = self.base_config.get("table_output")
        if table_output is not None:
            if not isinstance(table_output, str):
                raise ProviderConfigError("PyMuPDF4LLM 'table_output' must be a string")
            normalized_table_output = table_output.strip().lower()
            if normalized_table_output not in ("markdown", "html"):
                raise ProviderConfigError("PyMuPDF4LLM 'table_output' must be 'markdown' or 'html'")
            # Opt-in HTML table rendering. pymupdf4llm builds that ship the native
            # HTML table engine emit structured <table> markup for table_output="html";
            # builds without it ignore the extra keyword, so the default markdown
            # pipelines above are unaffected.
            options["table_output"] = normalized_table_output

        raw_backend = self.base_config.get("ocr_backend")
        if raw_backend is None:
            return options
        # `ocr_backend` selects a bundled pymupdf4llm OCR engine. It is a
        # ParseBench-level string, not a to_markdown kwarg: validate it here so a
        # bad value fails fast, but resolve the engine callable lazily at call
        # time (see `_resolve_ocr_function`) so it never enters this options
        # dict. `auto` defers to pymupdf4llm's own engine selection.
        if not isinstance(raw_backend, str):
            raise ProviderConfigError("PyMuPDF4LLM 'ocr_backend' must be a string")
        backend = raw_backend.strip().lower()
        if backend != "auto" and backend not in _OCR_BACKEND_MODULES:
            supported = ", ".join(["auto", *_OCR_BACKEND_MODULES])
            raise ProviderConfigError(
                f"Unsupported PyMuPDF4LLM OCR backend '{raw_backend}'. Supported backends: {supported}"
            )
        return options

    def _resolve_ocr_function(self) -> Callable[..., Any] | None:
        """Resolve the configured OCR engine callable immediately before OCR.

        `ocr_backend` is validated in `_markdown_options`; here the selected
        engine module is imported and its ``exec_ocr`` returned so it can be
        handed to ``to_markdown(ocr_function=...)`` as a direct call-time kwarg
        -- never stored in the serialized options/config dict. An absent or
        ``auto`` backend returns ``None`` so pymupdf4llm performs its own engine
        selection. Engine availability is discovered reactively: an unavailable
        backend raises ProviderConfigError only when that backend is actually
        requested, rather than probing eagerly for every request.
        """
        raw_backend = self.base_config.get("ocr_backend")
        if not isinstance(raw_backend, str):
            return None
        module_name = _OCR_BACKEND_MODULES.get(raw_backend.strip().lower())
        if module_name is None:
            return None
        try:
            ocr_module = importlib.import_module(module_name)
        except (ImportError, RuntimeError) as e:
            raise ProviderConfigError(f"PyMuPDF4LLM OCR backend '{raw_backend}' is unavailable: {e}") from e
        ocr_function = getattr(ocr_module, "exec_ocr", None)
        if not callable(ocr_function):
            raise ProviderConfigError(f"PyMuPDF4LLM OCR backend '{raw_backend}' does not expose exec_ocr")
        # The tesseract backend module imports cleanly even when Tesseract is
        # missing: it warns once and its exec_ocr becomes a per-page no-op
        # (pymupdf4llm/ocr/tesseract_api.py), so the import guard above never
        # fires for it. A benchmark run must not silently score without the OCR
        # the user asked for, so read the module's import-time availability
        # marker (no extra subprocess probe) and fail loudly instead.
        if getattr(ocr_module, "TESSDATA", True) is None:
            raise ProviderConfigError(
                f"PyMuPDF4LLM OCR backend '{raw_backend}' is unavailable: "
                "Tesseract language data was not found (pymupdf.get_tessdata() returned None)"
            )
        return ocr_function

    def _extract(self, pdf_path: str) -> dict[str, Any]:
        try:
            import pymupdf
            import pymupdf4llm  # type: ignore[import-untyped]
        except ImportError as e:
            raise ProviderConfigError("pymupdf4llm not installed. Run: pip install pymupdf4llm") from e

        try:
            markdown_options = self._markdown_options()
            # Resolve the OCR engine callable here, immediately before the call,
            # and pass it as a direct kwarg so the callable never lives in the
            # declarative options dict (ocr_backend stays a plain string key).
            ocr_function = self._resolve_ocr_function()
            if ocr_function is None:
                page_chunks = pymupdf4llm.to_markdown(pdf_path, **markdown_options)
            else:
                page_chunks = pymupdf4llm.to_markdown(pdf_path, ocr_function=ocr_function, **markdown_options)
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
        import markdown2

        lines = content.split("\n")
        result_parts: list[str] = []
        table_lines: list[str] = []
        in_table = False

        def _flush() -> None:
            nonlocal table_lines
            if len(table_lines) >= 2:
                html = markdown2.markdown("\n".join(table_lines), extras=["tables"]).strip()
                if "<table>" in html.lower():
                    result_parts.append(html)
                else:
                    result_parts.extend(table_lines)
            else:
                result_parts.extend(table_lines)
            table_lines = []

        for line in lines:
            if "|" in line and line.strip().startswith("|"):
                in_table = True
                table_lines.append(line)
            else:
                if in_table:
                    _flush()
                    in_table = False
                result_parts.append(line)
        if in_table:
            _flush()
        return "\n".join(result_parts)

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
        for page_box in page_data.get("page_boxes", []):
            if not isinstance(page_box, dict):
                continue

            # Emit the raw pymupdf4llm boxclass label untouched. Canonicalization
            # and failing loud on genuinely unknown classes are owned by the
            # evaluation label-mapper layer (PyMuPDF4LLMLabelMapper), not the
            # provider, so no class is silently dropped here.
            raw_label = str(page_box.get("class", "")).strip()
            if not raw_label:
                continue
            normalized_class = raw_label.lower().replace("_", "-")

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
                label=raw_label,
                start_index=start_index,
                end_index=end_index,
            )

            if normalized_class == "table":
                item_type = "table"
                # If the sliced content is already native HTML (e.g. a pipeline
                # opted into table_output="html"), keep it verbatim; otherwise
                # convert Markdown pipe tables via markdown2.
                item_html = content if "<table" in content.lower() else cls._convert_md_tables_to_html(content)
            elif normalized_class == "picture":
                item_type = "image"
                item_html = ""
            else:
                # Field-grounding evaluation consumes text-like items while the
                # raw provider category remains on the segment label.
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
