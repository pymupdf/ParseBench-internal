"""Shared helpers for the PyMuPDF source-stack GitHub workflow."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LAYOUT_REPOSITORIES = (
    "ArtifexSoftware/pymupdf_layout",
    "ArtifexSoftware/sce",
)

COMPONENTS = {
    "pymupdf": {
        "label": "PyMuPDF",
        "repository": "pymupdf/PyMuPDF",
        "root": Path(".source/pymupdf"),
    },
    "pymupdf_layout": {
        "label": "PyMuPDF Layout",
        "repository": LAYOUT_REPOSITORIES[0],
        "root": Path(".source/pymupdf-layout"),
    },
    "pymupdf4llm": {
        "label": "PyMuPDF4LLM",
        "repository": "pymupdf/pymupdf4llm",
        "root": Path(".source/pymupdf4llm"),
    },
}

DATASET_REPOSITORY = "llamaindex/ParseBench"
DATASET_BRANCHES = {
    "full": "main",
    "test": "test-data",
}


def env(name: str) -> str:
    """Return a required environment variable with a useful error."""
    try:
        return os.environ[name]
    except KeyError as error:
        raise SystemExit(f"Required environment variable {name} is not set") from error


def git_sha(path: str | Path = ".") -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_github_outputs(values: Mapping[str, str]) -> None:
    """Append single-line values to the current step's GitHub output file."""
    output = Path(env("GITHUB_OUTPUT"))
    with output.open("a", encoding="utf-8") as stream:
        for name, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError(f"GitHub output {name!r} must be a single line")
            stream.write(f"{name}={value}\n")


def append_summary(lines: list[str]) -> None:
    with Path(env("GITHUB_STEP_SUMMARY")).open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")
