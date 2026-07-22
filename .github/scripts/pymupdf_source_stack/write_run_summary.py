#!/usr/bin/env python3
"""Put the requested and resolved source configuration at the top of the run summary."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from common import COMPONENTS, append_summary, env, git_sha, markdown_cell


@dataclass(frozen=True)
class SourceRevision:
    label: str
    repository: str
    requested_ref: str
    sha: str
    commit_date: str
    commits_after: int | None


def commit_date(root: object) -> str:
    value = subprocess.check_output(
        ["git", "-C", str(root), "show", "-s", "--format=%cI", "HEAD"],
        text=True,
    ).strip()
    parsed = datetime.fromisoformat(value).astimezone(UTC)
    return parsed.strftime("%Y-%m-%d %H:%M:%S UTC")


def commits_after_main(repository: str, sha: str, token: str) -> int | None:
    comparison = f"{quote(sha, safe='')}...main"
    request = Request(  # noqa: S310 - fixed GitHub API host
        f"https://api.github.com/repos/{repository}/compare/{comparison}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "ParseBench-source-stack-workflow",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API host
            metadata = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    count = metadata.get("ahead_by")
    return count if isinstance(count, int) and count >= 0 else None


def github_link(label: str, repository: str, suffix: str = "") -> str:
    url = f"https://github.com/{repository}{suffix}"
    return f"[{markdown_cell(label)}]({url})"


def commit_label(commits_after: int | None) -> str:
    if commits_after == 0:
        return "Latest commit"
    if commits_after == 1:
        return "1 commit ago"
    if commits_after is not None:
        return f"{commits_after} commits ago"
    return "Selected commit"


def source_table(
    revisions: list[SourceRevision],
    all_latest: bool,
    latest_any_branch: bool = False,
) -> list[str]:
    lines = ["### PyMuPDF source commits", ""]
    if latest_any_branch:
        lines.extend(
            [
                "The newest branch-head commit was requested from each PyMuPDF repository.",
                "",
                "| Component | Repository | Branch selected | Commit used | Commit date |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        lines.extend(
            f"| {markdown_cell(revision.label)} | "
            f"{github_link(revision.repository, revision.repository)} | "
            f"`{markdown_cell(revision.requested_ref)}` | "
            f"{github_link('Latest branch-head commit', revision.repository, f'/commit/{revision.sha}')} | "
            f"{markdown_cell(revision.commit_date)} |"
            for revision in revisions
        )
        return lines
    if all_latest:
        lines.extend(
            [
                "Latest commits were requested for all three PyMuPDF repositories.",
                "",
                "| Component | Repository | Commit used | Commit date |",
                "| --- | --- | --- | --- |",
            ]
        )
        lines.extend(
            f"| {markdown_cell(revision.label)} | "
            f"{github_link(revision.repository, revision.repository)} | "
            f"{github_link('Latest commit', revision.repository, f'/commit/{revision.sha}')} | "
            f"{markdown_cell(revision.commit_date)} |"
            for revision in revisions
        )
        return lines

    lines.extend(
        [
            "| Component | Repository | Requested selection | Commit used | Commit date |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for revision in revisions:
        lines.append(
            f"| {markdown_cell(revision.label)} | "
            f"{github_link(revision.repository, revision.repository)} | "
            f"`{markdown_cell(revision.requested_ref)}` | "
            f"{github_link(commit_label(revision.commits_after), revision.repository, f'/commit/{revision.sha}')} | "
            f"{markdown_cell(revision.commit_date)} |"
        )
    return lines


def main() -> int:
    all_latest = env("ALL_LATEST").strip().lower() == "true"
    latest_any_branch = env("LATEST_ANY_BRANCH").strip().lower() == "true"
    refs = {
        "pymupdf": env("PYMUPDF_REF"),
        "pymupdf_layout": env("PYMUPDF_LAYOUT_REF"),
        "pymupdf4llm": env("PYMUPDF4LLM_REF"),
    }
    token = env("GITHUB_TOKEN")
    revisions = []
    for name, component in COMPONENTS.items():
        repository = (
            env("PYMUPDF_LAYOUT_REPOSITORY")
            if name == "pymupdf_layout"
            else str(component["repository"])
        )
        sha = git_sha(component["root"])
        revisions.append(
            SourceRevision(
                label=str(component["label"]),
                repository=repository,
                requested_ref=refs[name],
                sha=sha,
                commit_date=commit_date(component["root"]),
                commits_after=None
                if all_latest or latest_any_branch
                else commits_after_main(repository, sha, token),
            )
        )

    benchmark_repository = env("GITHUB_REPOSITORY")
    benchmark_sha = git_sha()
    dataset_repository = env("DATASET_REPOSITORY")
    dataset_sha = env("DATASET_SHA")
    lines = [
        "## What this run is testing",
        "",
        f"- **Test size:** {markdown_cell(env('RUN_SCOPE_SELECTION'))}",
        f"- **Document category:** {markdown_cell(env('GROUP_SELECTION'))}",
        f"- **Pipeline:** {markdown_cell(env('PIPELINE'))}",
        "- **Dataset download:** immutable SHA cache; downloads only on a cache miss",
        "- **MuPDF:** selected automatically by the chosen PyMuPDF revision",
        "",
        *source_table(revisions, all_latest, latest_any_branch),
        "",
        "### Benchmark revisions",
        "",
        "| Component | Repository | Requested selection | Commit used |",
        "| --- | --- | --- | --- |",
        f"| ParseBench | {github_link(benchmark_repository, benchmark_repository)} | "
        f"`{markdown_cell(env('BENCHMARK_REF'))}` | "
        f"{github_link('Workflow commit', benchmark_repository, f'/commit/{benchmark_sha}')} |",
        f"| ParseBench dataset | `{markdown_cell(dataset_repository)}` | "
        f"`{markdown_cell(env('DATASET_REQUESTED_REF'))}` | "
        f"[{'Current dataset commit' if env('DATASET_REQUESTED_REF') == 'current' else 'Selected dataset commit'}]"
        f"(https://huggingface.co/datasets/{dataset_repository}/commit/{dataset_sha}) |",
        "",
    ]
    append_summary(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
