#!/usr/bin/env python3
"""Write success or incomplete status to the final workflow summary."""

from __future__ import annotations

import argparse

from common import append_summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("status", choices=("success", "incomplete"))
    parser.add_argument("--benchmark-result", default="success")
    parser.add_argument("--publish-result", default="success")
    args = parser.parse_args()

    if args.status == "success":
        lines = [
            "## Workflow completed successfully",
            "",
            "- Benchmark: **successful**",
            "- Results publishing: **successful**",
        ]
    else:
        lines = [
            "## Workflow did not complete",
            "",
            f"- Benchmark job: **{args.benchmark_result}**",
            f"- Publishing job: **{args.publish_result}**",
        ]
    append_summary(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
