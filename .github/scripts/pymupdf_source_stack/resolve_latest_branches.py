#!/usr/bin/env python3
"""Resolve the newest branch-head commit in each PyMuPDF source repository."""

from __future__ import annotations

import base64
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from common import COMPONENTS, LAYOUT_REPOSITORIES, env, write_github_outputs, write_json

FULL_SHA = re.compile(r"[0-9a-f]{40}")
LATEST_LAYOUT_REPOSITORY = LAYOUT_REPOSITORIES[-1]


@dataclass(frozen=True)
class BranchHead:
    branch: str
    sha: str
    committed_at: int


def parse_branch_heads(output: str, repository: str) -> BranchHead:
    heads: list[BranchHead] = []
    for line in output.splitlines():
        try:
            branch, sha, timestamp = line.split("\t", 2)
            committed_at = int(timestamp)
        except ValueError as error:
            raise SystemExit(f"Git returned an invalid branch head for {repository}: {line!r}") from error
        if not branch or not FULL_SHA.fullmatch(sha) or committed_at < 0:
            raise SystemExit(f"Git returned an invalid branch head for {repository}: {line!r}")
        heads.append(BranchHead(branch=branch, sha=sha, committed_at=committed_at))

    if not heads:
        raise SystemExit(f"No branch heads were found in {repository}")

    # Commit time is the only branch-local recency timestamp stored by Git.
    # The branch name and SHA make ties deterministic.
    return max(heads, key=lambda head: (head.committed_at, head.branch, head.sha))


def latest_branch_head(repository: str, token: str) -> BranchHead:
    authorization = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    with tempfile.TemporaryDirectory(prefix="parsebench-latest-branch-") as temp_dir:
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
                "--filter=tree:0",
                "--no-tags",
                "https://github.com/" + repository + ".git",
                "+refs/heads/*:refs/remotes/source/*",
            ],
            check=False,
            capture_output=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown Git error"
            raise SystemExit(f"Could not fetch branch heads from {repository}: {detail}")
        output = subprocess.check_output(
            [
                "git",
                "-C",
                temp_dir,
                "for-each-ref",
                "--format=%(refname:lstrip=3)\t%(objectname)\t%(committerdate:unix)",
                "refs/remotes/source",
            ],
            text=True,
        )
    return parse_branch_heads(output, repository)


def source_repositories() -> dict[str, str]:
    return {
        name: LATEST_LAYOUT_REPOSITORY if name == "pymupdf_layout" else str(component["repository"])
        for name, component in COMPONENTS.items()
    }


def main() -> int:
    output_dir = Path(env("OUTPUT_DIR"))
    token = env("GITHUB_TOKEN")
    resolved: dict[str, dict[str, str | int]] = {}
    outputs: dict[str, str] = {"pymupdf_layout_repository": LATEST_LAYOUT_REPOSITORY}

    for name, repository in source_repositories().items():
        try:
            head = latest_branch_head(repository, token)
        except (OSError, subprocess.SubprocessError, SystemExit) as error:
            message = f"Could not resolve the latest branch head for {repository}: {error}"
            write_json(
                output_dir / "_failure.json",
                {
                    "title": "Cannot resolve latest source branch",
                    "error": message,
                    "component": str(COMPONENTS[name]["label"]),
                    "repository": repository,
                    "details": (
                        "The latest-any-branch run stopped before source checkout. Verify repository "
                        "access and retry the workflow."
                    ),
                },
            )
            raise SystemExit(message) from error

        resolved[name] = {
            "selection": "latest_any_branch",
            "repository": repository,
            "branch": head.branch,
            "ref": head.branch,
            "resolved_sha": head.sha,
            "commit_timestamp": head.committed_at,
        }
        outputs[f"{name}_branch"] = head.branch
        outputs[f"{name}_sha"] = head.sha

    write_json(output_dir / "_source_request.json", resolved)
    write_json(output_dir / "_latest_branch_heads.json", resolved)
    write_github_outputs(outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
