#!/usr/bin/env python3
"""Put the requested and resolved source configuration at the top of the run summary."""

from __future__ import annotations

from common import COMPONENTS, append_summary, env, git_sha, markdown_cell


def main() -> int:
    refs = {
        "pymupdf": env("PYMUPDF_REF"),
        "pymupdf_layout": env("PYMUPDF_LAYOUT_REF"),
        "pymupdf4llm": env("PYMUPDF4LLM_REF"),
    }
    rows = [
        ("ParseBench", env("GITHUB_REPOSITORY"), env("BENCHMARK_REF"), git_sha()),
        *(
            (
                str(component["label"]),
                str(component["repository"]),
                refs[name],
                git_sha(component["root"]),
            )
            for name, component in COMPONENTS.items()
        ),
        (
            "ParseBench dataset",
            env("DATASET_REPOSITORY"),
            env("DATASET_BRANCH"),
            env("DATASET_SHA"),
        ),
    ]
    lines = [
        "## What this run is testing",
        "",
        f"- **Test size:** {markdown_cell(env('RUN_SCOPE_SELECTION'))}",
        f"- **Document category:** {markdown_cell(env('GROUP_SELECTION'))}",
        f"- **Pipeline:** {markdown_cell(env('PIPELINE'))}",
        "- **Dataset download:** immutable SHA cache; downloads only on a cache miss",
        "- **MuPDF:** selected automatically by the chosen PyMuPDF revision",
        "",
        "| Component | Repository | Requested selection | Exact commit used |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {markdown_cell(component)} | `{markdown_cell(repository)}` | "
        f"`{markdown_cell(requested)}` | `{markdown_cell(commit)}` |"
        for component, repository, requested, commit in rows
    )
    lines.append("")
    append_summary(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
