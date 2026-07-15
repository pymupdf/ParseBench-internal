#!/usr/bin/env python3
"""Write a concise GitHub Actions failure explanation to the run summary."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+")
EXCEPTION_RE = re.compile(r"^(?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*(?:Error|Exception):\s")
ERROR_MARKERS = (
    "##[error]",
    "::error",
    "error:",
    "exception:",
    "fatal:",
    "process completed with exit code",
)
MAX_JOB_DETAILS = 80_000


def _clean_log_line(line: str) -> str:
    line = ANSI_RE.sub("", line)
    return TIMESTAMP_RE.sub("", line).rstrip()


def decode_job_log(data: bytes) -> str:
    """Decode either GitHub's plain-text job log or a ZIP log response."""
    stream = io.BytesIO(data)
    if zipfile.is_zipfile(stream):
        with zipfile.ZipFile(stream) as archive:
            parts = []
            for name in sorted(archive.namelist()):
                if name.endswith("/"):
                    continue
                parts.append(archive.read(name).decode("utf-8", errors="replace"))
            return "\n".join(parts)
    return data.decode("utf-8", errors="replace")


def extract_error_details(log: str) -> str:
    """Extract complete Python tracebacks and useful context around error markers."""
    lines = [_clean_log_line(line) for line in log.splitlines()]
    ranges: list[tuple[int, int]] = []

    for index, line in enumerate(lines):
        if "Traceback (most recent call last):" not in line:
            continue
        end = min(len(lines), index + 160)
        for cursor in range(index + 1, end):
            if EXCEPTION_RE.match(lines[cursor].strip()):
                end = cursor + 1
                break
        ranges.append((index, end))

    for index, line in enumerate(lines):
        lowered = line.lower()
        if any(marker in lowered for marker in ERROR_MARKERS):
            ranges.append((max(0, index - 4), min(len(lines), index + 5)))

    if not ranges:
        ranges.append((max(0, len(lines) - 80), len(lines)))

    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    sections = []
    for start, end in merged:
        text = "\n".join(line for line in lines[start:end] if line)
        if text:
            sections.append(text)
    details = "\n\n...\n\n".join(sections)
    if len(details) > MAX_JOB_DETAILS:
        details = details[:MAX_JOB_DETAILS] + "\n\n[Error details truncated to fit the GitHub summary.]"
    return details


def _api_get(url: str, token: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed GitHub API URL
        return response.read()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def _download_job_log(url: str, token: str) -> bytes:
    """Download a job log without forwarding the GitHub token to signed storage."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=60) as response:  # noqa: S310 - fixed GitHub API URL
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code not in {301, 302, 303, 307, 308} or not error.headers.get("Location"):
            raise
        signed_url = error.headers["Location"]
        clean_request = urllib.request.Request(signed_url, headers={"Accept": "text/plain"})
        with urllib.request.urlopen(clean_request, timeout=60) as response:  # noqa: S310 - GitHub signed URL
            return response.read()


def _compatibility_failures(diagnostics: Path) -> list[dict[str, Any]]:
    failures = []
    if not diagnostics.exists():
        return failures
    for path in diagnostics.rglob("_compatibility.json"):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if result.get("status") == "incompatible":
            failures.append(result)
    return failures


def _structured_failures(diagnostics: Path) -> list[dict[str, Any]]:
    failures = []
    if not diagnostics.exists():
        return failures
    for path in diagnostics.rglob("_failure.json"):
        try:
            failures.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return failures


def build_summary(
    *,
    jobs: list[dict[str, Any]],
    logs: dict[int, str],
    diagnostics: Path,
    run_url: str,
    benchmark_result: str,
    publish_result: str,
) -> str:
    """Build the Markdown shown on the GitHub Actions run summary page."""
    failed_jobs = [job for job in jobs if job.get("conclusion") == "failure"]
    lines = [
        "## Why this workflow failed",
        "",
        f"[Open the workflow run]({run_url})",
        "",
        f"- Benchmark job: **{benchmark_result}**",
        f"- Publishing job: **{publish_result}**",
    ]

    for failure in _structured_failures(diagnostics):
        lines.extend(
            [
                "",
                f"### {failure.get('title', 'Failure reason')}",
                "",
                str(failure.get("error", "The workflow could not continue.")),
            ]
        )
        if failure.get("requested_ref"):
            lines.append(f"- Requested selection: `{failure['requested_ref']}`")
        if failure.get("resolved_sha"):
            lines.append(f"- Resolved commit: `{failure['resolved_sha']}`")
        if failure.get("details"):
            lines.extend(["", str(failure["details"])])

    compatibility = _compatibility_failures(diagnostics)
    for result in compatibility:
        lines.extend(
            [
                "",
                "### Compatibility exception",
                "",
                str(result.get("error", "The selected source stack is incompatible.")),
            ]
        )
        traceback = result.get("traceback")
        if traceback:
            lines.extend(["", "````text", str(traceback).rstrip(), "````"])

    for job in failed_jobs:
        job_id = int(job["id"])
        failed_steps = [
            str(step.get("name", "Unknown step"))
            for step in job.get("steps", [])
            if step.get("conclusion") == "failure"
        ]
        lines.extend(["", f"### Failed job: {job.get('name', job_id)}", ""])
        if failed_steps:
            lines.append(f"- Failed step{'s' if len(failed_steps) != 1 else ''}: **{', '.join(failed_steps)}**")

        details = extract_error_details(logs[job_id]) if job_id in logs else ""
        if details:
            lines.extend(["", "#### Error details", "", "````text", details, "````"])
        else:
            lines.extend(["", "The detailed job log could not be downloaded. Use the workflow link above."])

    if not failed_jobs:
        lines.extend(["", "GitHub did not report a failed job. Use the workflow link above for details."])
    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--benchmark-result", required=True)
    parser.add_argument("--publish-result", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    token = os.environ["GH_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]
    run_id = os.environ["GITHUB_RUN_ID"]
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"

    jobs_url = f"{api_url}/repos/{repository}/actions/runs/{run_id}/jobs?filter=all&per_page=100"
    jobs: list[dict[str, Any]] = []
    logs: dict[int, str] = {}
    try:
        jobs = json.loads(_api_get(jobs_url, token))["jobs"]
        for job in jobs:
            if job.get("conclusion") != "failure":
                continue
            job_id = int(job["id"])
            try:
                data = _download_job_log(f"{api_url}/repos/{repository}/actions/jobs/{job_id}/logs", token)
                logs[job_id] = decode_job_log(data)
            except Exception as error:  # Keep the summary job alive and show the fallback link.
                logs[job_id] = f"Unable to download the completed job log: {type(error).__name__}: {error}"
    except Exception as error:  # Keep the summary job alive and show the fallback link.
        jobs = []
        logs = {}
        print(f"Unable to query failed jobs: {type(error).__name__}: {error}")

    summary = build_summary(
        jobs=jobs,
        logs=logs,
        diagnostics=args.diagnostics,
        run_url=run_url,
        benchmark_result=args.benchmark_result,
        publish_result=args.publish_result,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as output:
        output.write(summary)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
