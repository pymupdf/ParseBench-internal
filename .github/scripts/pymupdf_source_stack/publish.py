#!/usr/bin/env python3
"""Publish completed results or failure diagnostics to the configured GCS bucket."""

from __future__ import annotations

import subprocess
from pathlib import Path

from common import append_summary, env


def main() -> int:
    bucket = env("BUCKET")
    if not bucket:
        raise SystemExit("PARSEBENCH_GCS_BUCKET repository variable is not set")
    output_dir = Path(env("OUTPUT_DIR"))
    if not any(path.is_file() for path in output_dir.rglob("*")):
        raise SystemExit(f"No output files found in {output_dir}")

    destination = env("DESTINATION")
    output_uri = f"gs://{bucket}/{destination}/parsebench-output/"
    public_url = f"https://storage.googleapis.com/{bucket}/{destination}/parsebench-output/"
    subprocess.run(
        ["gcloud", "storage", "cp", "--recursive", str(output_dir), f"gs://{bucket}/{destination}/"],
        check=True,
    )

    succeeded = env("BENCHMARK_RESULT") == "success"
    lines = [
        "## Benchmark results published" if succeeded else "## Failure diagnostics published",
        "",
        f"- GCS path: `{output_uri}`",
    ]
    if not succeeded:
        lines.append(
            "- No completed benchmark results were published; "
            "this location contains diagnostics and any partial output."
        )
    elif (output_dir / "_leaderboard.html").is_file():
        lines.append(f"- Public leaderboard HTML: [download _leaderboard.html]({public_url}_leaderboard.html)")
    else:
        lines.append("- Public leaderboard HTML: not generated for this run")
    append_summary(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
