#!/usr/bin/env python3
"""Smoke-test a source-built PyMuPDF / Layout / PyMuPDF4LLM stack."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import tempfile
import traceback
from pathlib import Path
from typing import Any

SMOKE_TEXT = "ParseBench source stack compatibility check"


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _github_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _source_metadata(args: argparse.Namespace) -> dict[str, dict[str, str]]:
    return {
        "pymupdf": {
            "repository": args.pymupdf_repository,
            "requested_ref": args.pymupdf_ref,
            "resolved_sha": args.pymupdf_sha,
        },
        "pymupdf_layout": {
            "repository": args.pymupdf_layout_repository,
            "requested_ref": args.pymupdf_layout_ref,
            "resolved_sha": args.pymupdf_layout_sha,
        },
        "pymupdf4llm": {
            "repository": args.pymupdf4llm_repository,
            "requested_ref": args.pymupdf4llm_ref,
            "resolved_sha": args.pymupdf4llm_sha,
        },
    }


def _installed_versions() -> dict[str, str | None]:
    return {
        "pymupdf": _distribution_version("PyMuPDF"),
        "pymupdf_layout": _distribution_version("pymupdf-layout"),
        "pymupdf4llm": _distribution_version("pymupdf4llm"),
    }


def _make_smoke_pdf(path: Path) -> None:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), SMOKE_TEXT, fontsize=14)
    page.insert_text((72, 108), "Column A", fontsize=10)
    page.insert_text((220, 108), "Column B", fontsize=10)
    page.insert_text((72, 132), "alpha", fontsize=10)
    page.insert_text((220, 132), "beta", fontsize=10)
    page.draw_rect(pymupdf.Rect(64, 90, 340, 146), color=(0, 0, 0), width=1)
    page.draw_line((64, 118), (340, 118), color=(0, 0, 0), width=1)
    page.draw_line((200, 90), (200, 146), color=(0, 0, 0), width=1)
    document.save(path)
    document.close()


def run_compatibility_check() -> dict[str, Any]:
    import pymupdf
    import pymupdf.layout

    pymupdf.layout.activate()

    import pymupdf4llm

    if getattr(pymupdf4llm, "_use_layout", True) is not True:
        raise RuntimeError("PyMuPDF4LLM imported, but Layout mode is disabled")

    if not callable(getattr(pymupdf, "_get_layout", None)):
        raise RuntimeError("pymupdf.layout.activate() did not install the PyMuPDF layout callback")

    with tempfile.TemporaryDirectory(prefix="parsebench-pymupdf-compat-") as temp_dir:
        smoke_pdf = Path(temp_dir) / "compatibility.pdf"
        _make_smoke_pdf(smoke_pdf)
        chunks = pymupdf4llm.to_markdown(
            smoke_pdf,
            page_chunks=True,
            show_progress=False,
            use_ocr=False,
            ocr_dpi=150,
        )

    if not isinstance(chunks, list) or len(chunks) != 1:
        raise RuntimeError(f"Expected one page chunk, received {type(chunks).__name__}: {chunks!r}")

    chunk = chunks[0]
    if not isinstance(chunk, dict):
        raise RuntimeError(f"Expected a dictionary page chunk, received {type(chunk).__name__}")

    text = chunk.get("text")
    if not isinstance(text, str) or SMOKE_TEXT not in text:
        raise RuntimeError("PyMuPDF4LLM output did not contain the compatibility marker text")

    page_boxes = chunk.get("page_boxes")
    if not isinstance(page_boxes, list) or not page_boxes:
        raise RuntimeError("PyMuPDF4LLM output did not contain non-empty Layout page_boxes")

    return {
        "layout_mode": True,
        "page_box_count": len(page_boxes),
        "page_chunk_count": len(chunks),
        "smoke_text_found": True,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pymupdf-repository", required=True)
    parser.add_argument("--pymupdf-ref", required=True)
    parser.add_argument("--pymupdf-sha", required=True)
    parser.add_argument("--pymupdf-layout-repository", required=True)
    parser.add_argument("--pymupdf-layout-ref", required=True)
    parser.add_argument("--pymupdf-layout-sha", required=True)
    parser.add_argument("--pymupdf4llm-repository", required=True)
    parser.add_argument("--pymupdf4llm-ref", required=True)
    parser.add_argument("--pymupdf4llm-sha", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result: dict[str, Any] = {
        "python": platform.python_version(),
        "sources": _source_metadata(args),
    }

    try:
        result["installed_versions"] = _installed_versions()
        result["checks"] = run_compatibility_check()
        result["status"] = "compatible"
    except Exception as error:
        result["installed_versions"] = _installed_versions()
        result["status"] = "incompatible"
        result["error"] = f"{type(error).__name__}: {error}"
        result["traceback"] = traceback.format_exc()
        print(f"::error title=Incompatible PyMuPDF source stack::{_github_escape(result['error'])}")
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))

    return 0 if result["status"] == "compatible" else 1


if __name__ == "__main__":
    raise SystemExit(main())
