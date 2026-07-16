#!/usr/bin/env python3
"""Resolve the selected Hugging Face dataset branch to an immutable commit."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from common import DATASET_BRANCHES, DATASET_REPOSITORY, env, write_github_outputs, write_json

FULL_SHA = re.compile(r"[0-9a-f]{40}")
CURRENT = "current"


def branch_for_scope(run_scope: str) -> str:
    try:
        return DATASET_BRANCHES[run_scope]
    except KeyError as error:
        choices = ", ".join(sorted(DATASET_BRANCHES))
        raise SystemExit(f"Unsupported dataset scope {run_scope!r}. Expected one of: {choices}") from error


def resolve_branch(repository: str, branch: str) -> str:
    remote = f"https://huggingface.co/datasets/{repository}.git"
    ref = f"refs/heads/{branch}"
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", remote, ref],
        check=True,
        capture_output=True,
        text=True,
    )
    fields = result.stdout.split()
    if len(fields) != 2 or fields[1] != ref or not FULL_SHA.fullmatch(fields[0]):
        raise SystemExit(f"Could not resolve Hugging Face dataset branch {repository}@{branch}")
    return fields[0]


def validate_commit(repository: str, sha: str) -> str:
    url = f"https://huggingface.co/api/datasets/{repository}/revision/{sha}"
    try:
        with urlopen(url, timeout=30) as response:  # noqa: S310 - fixed trusted host
            metadata = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            raise SystemExit(f"Hugging Face dataset commit {repository}@{sha} does not exist") from error
        raise SystemExit(f"Hugging Face rejected dataset commit {repository}@{sha}: HTTP {error.code}") from error
    except URLError as error:
        raise SystemExit(f"Could not validate Hugging Face dataset commit {repository}@{sha}: {error}") from error

    resolved = metadata.get("sha")
    if resolved != sha:
        raise SystemExit(f"Hugging Face returned unexpected revision {resolved!r} for {repository}@{sha}")
    return sha


def main() -> int:
    repository = DATASET_REPOSITORY
    branch = branch_for_scope(env("RUN_SCOPE"))
    requested_ref = env("DATASET_REF").strip().lower()
    if requested_ref == CURRENT:
        sha = resolve_branch(repository, branch)
    elif FULL_SHA.fullmatch(requested_ref):
        sha = validate_commit(repository, requested_ref)
    else:
        raise SystemExit(
            f"Unsupported dataset version {requested_ref!r}. Use {CURRENT!r} or a full 40-character commit SHA."
        )
    commit_url = f"https://huggingface.co/datasets/{repository}/commit/{sha}"

    dataset = {
        "branch": branch,
        "commit_url": commit_url,
        "repository": repository,
        "requested_ref": requested_ref,
        "resolved_sha": sha,
    }
    write_json(Path(env("OUTPUT_DIR")) / "_dataset.json", dataset)
    write_github_outputs(
        {
            "branch": branch,
            "commit_url": commit_url,
            "repository": repository,
            "requested_ref": requested_ref,
            "sha": sha,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
