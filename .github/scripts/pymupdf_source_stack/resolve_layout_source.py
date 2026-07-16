#!/usr/bin/env python3
"""Resolve a PyMuPDF Layout ref across the current and legacy repositories."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from common import LAYOUT_REPOSITORIES, env, write_github_outputs, write_json

FULL_SHA = re.compile(r"[0-9a-f]{40}")
HTTP_STATUS = re.compile(r"HTTP (\d{3})")


def resolve_commit_with_git(repository: str, requested_ref: str, token: str) -> str | None:
    authorization = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    with tempfile.TemporaryDirectory(prefix="parsebench-layout-ref-") as temp_dir:
        subprocess.run(["git", "-C", temp_dir, "init", "--quiet"], check=True)
        result = subprocess.run(
            [
                "git",
                "-C",
                temp_dir,
                "-c",
                f"http.extraHeader=AUTHORIZATION: basic {authorization}",
                "fetch",
                "--quiet",
                "--depth=1",
                "--no-tags",
                f"https://github.com/{repository}.git",
                requested_ref,
            ],
            check=False,
            capture_output=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            text=True,
        )
        if result.returncode != 0:
            return None
        sha = subprocess.check_output(
            ["git", "-C", temp_dir, "rev-parse", "FETCH_HEAD"],
            text=True,
        ).strip()
    return sha if FULL_SHA.fullmatch(sha) else None


def resolve_commit(repository: str, requested_ref: str, token: str) -> str | None:
    encoded_ref = quote(requested_ref, safe="")
    request = Request(  # noqa: S310 - fixed GitHub API host
        f"https://api.github.com/repos/{repository}/commits/{encoded_ref}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "ParseBench-source-stack-workflow",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API host
                metadata = json.load(response)
            break
        except HTTPError as error:
            if error.code == 404:
                return None
            if error.code >= 500 and attempt < 2:
                time.sleep(2**attempt)
                continue
            if error.code >= 500:
                fallback_sha = resolve_commit_with_git(repository, requested_ref, token)
                if fallback_sha is not None:
                    return fallback_sha
            raise SystemExit(f"GitHub rejected {repository}@{requested_ref}: HTTP {error.code}") from error
        except URLError as error:
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            fallback_sha = resolve_commit_with_git(repository, requested_ref, token)
            if fallback_sha is not None:
                return fallback_sha
            raise SystemExit(f"Could not resolve {repository}@{requested_ref}: {error}") from error

    sha = metadata.get("sha")
    if not isinstance(sha, str) or not FULL_SHA.fullmatch(sha):
        raise SystemExit(f"GitHub returned an invalid commit for {repository}@{requested_ref}: {sha!r}")
    return sha


def record_source_request(output_dir: Path, repository: str, requested_ref: str, sha: str) -> None:
    path = output_dir / "_source_request.json"
    request = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    request["pymupdf_layout"] = {
        "ref": requested_ref,
        "repository": repository,
        "resolved_sha": sha,
    }
    write_json(path, request)


def record_github_service_failure(
    output_dir: Path,
    repository: str,
    requested_ref: str,
    error: SystemExit,
) -> bool:
    """Record an actionable diagnostic for a transient GitHub API failure."""
    match = HTTP_STATUS.search(str(error))
    if match is None or int(match.group(1)) < 500:
        return False

    status = int(match.group(1))
    message = (
        f"GitHub's REST API was temporarily unavailable (HTTP {status}) while resolving "
        f"{repository}@{requested_ref}. This is an external GitHub service error, not a "
        "PyMuPDF source compatibility failure."
    )
    write_json(
        output_dir / "_failure.json",
        {
            "title": "GitHub API temporarily unavailable",
            "error": message,
            "component": "GitHub REST API",
            "repository": repository,
            "requested_ref": requested_ref,
            "http_status": status,
            "details": (
                "Source resolution could not finish, so compatibility checks and benchmark "
                "execution were skipped. Retry the workflow after GitHub's API service recovers."
            ),
        },
    )
    return True


def main() -> int:
    requested_ref = env("PYMUPDF_LAYOUT_REF").strip()
    output_dir = Path(env("OUTPUT_DIR"))
    token = env("GITHUB_TOKEN")

    for repository in LAYOUT_REPOSITORIES:
        try:
            sha = resolve_commit(repository, requested_ref, token)
        except SystemExit as error:
            if record_github_service_failure(output_dir, repository, requested_ref, error):
                raise SystemExit(
                    f"GitHub's REST API was temporarily unavailable while resolving "
                    f"{repository}@{requested_ref}; retry this workflow later."
                ) from error
            raise
        if sha is None:
            continue

        result = {
            "repository": repository,
            "requested_ref": requested_ref,
            "resolved_sha": sha,
        }
        write_json(output_dir / "_layout_source.json", result)
        record_source_request(output_dir, repository, requested_ref, sha)
        write_github_outputs({"repository": repository, "sha": sha})
        return 0

    repositories = ", ".join(LAYOUT_REPOSITORIES)
    error = (
        f"PyMuPDF Layout selection {requested_ref!r} was not found in {repositories}. "
        "Older refs require access to the legacy ArtifexSoftware/sce repository."
    )
    write_json(
        output_dir / "_failure.json",
        {
            "title": "Cannot resolve PyMuPDF Layout source",
            "error": error,
            "component": "PyMuPDF Layout",
            "requested_ref": requested_ref,
            "repositories": list(LAYOUT_REPOSITORIES),
        },
    )
    raise SystemExit(error)


if __name__ == "__main__":
    raise SystemExit(main())
