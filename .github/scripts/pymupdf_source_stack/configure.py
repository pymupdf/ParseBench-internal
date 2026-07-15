#!/usr/bin/env python3
"""Translate friendly workflow inputs into ParseBench run configuration."""

from __future__ import annotations

import re
from pathlib import Path

from common import COMPONENTS, env, write_github_outputs, write_json

RUN_SCOPES = {
    "Quick test (15 cases)": ("test", "data/test"),
    "Full benchmark (~2,000 pages)": ("full", "data"),
}
GROUPS = {
    "All categories": "all",
    "Charts": "chart",
    "Tables": "table",
    "Page layout": "layout",
    "Text content": "text_content",
    "Text formatting": "text_formatting",
}


def safe_ref(value: str) -> str:
    value = re.sub(r"[/:@ ]", "-", value)
    return re.sub(r"[^A-Za-z0-9._-]", "", value)[:48]


def selected(mapping: dict[str, object], value: str, label: str):
    try:
        return mapping[value]
    except KeyError as error:
        choices = ", ".join(mapping)
        raise SystemExit(f"Unsupported {label}: {value!r}. Expected one of: {choices}") from error


def main() -> int:
    benchmark_ref = env("BENCHMARK_REF")
    run_scope, data_dir = selected(RUN_SCOPES, env("RUN_SCOPE_SELECTION"), "test size")
    group = selected(GROUPS, env("GROUP_SELECTION"), "document category")
    refs = {
        "pymupdf": env("PYMUPDF_REF"),
        "pymupdf_layout": env("PYMUPDF_LAYOUT_REF"),
        "pymupdf4llm": env("PYMUPDF4LLM_REF"),
    }

    output_dir = Path(env("RUNNER_TEMP")) / "parsebench-output"
    output_dir.mkdir(parents=True, exist_ok=True)

    stack_label = "_".join(
        (
            f"pymupdf-{safe_ref(refs['pymupdf'])}",
            f"layout-{safe_ref(refs['pymupdf_layout'])}",
            f"4llm-{safe_ref(refs['pymupdf4llm'])}",
        )
    )
    prefix = env("GCS_PREFIX").strip("/")
    destination = (
        f"{prefix}/{stack_label}/{safe_ref(benchmark_ref)}"
        f"/run-{env('GITHUB_RUN_ID')}-attempt-{env('GITHUB_RUN_ATTEMPT')}"
    )
    artifact_name = f"pymupdf-source-stack-{env('GITHUB_RUN_ID')}-{env('GITHUB_RUN_ATTEMPT')}"

    request = {
        name: {"repository": component["repository"], "ref": refs[name]}
        for name, component in COMPONENTS.items()
    }
    write_json(output_dir / "_source_request.json", request)
    write_github_outputs(
        {
            "artifact_name": artifact_name,
            "benchmark_ref": benchmark_ref,
            "data_dir": data_dir,
            "destination": destination,
            "group": group,
            "output_dir": str(output_dir),
            "run_scope": run_scope,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
