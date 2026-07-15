#!/usr/bin/env python3
"""Run dataset, inference, evaluation, and reporting phases for the workflow."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from common import env


def run(*arguments: str) -> None:
    subprocess.run(arguments, check=True)


def parse_bench(*arguments: str) -> None:
    run("uv", "run", "parse-bench", *arguments)


def download() -> None:
    arguments = ["download"]
    if env("RUN_SCOPE") == "test":
        arguments.append("--test")
    parse_bench(*arguments)


def inference() -> None:
    arguments = [
        "inference",
        "run",
        env("PIPELINE"),
        "--input_dir",
        env("DATA_DIR"),
        "--output_dir",
        env("OUTPUT_DIR"),
        "--max_concurrent",
        "1",
    ]
    if env("GROUP") != "all":
        arguments.extend(("--group", env("GROUP")))
    parse_bench(*arguments)


def evaluation_groups(pipeline_output_dir: Path) -> list[str]:
    groups = {result.parent.name for result in pipeline_output_dir.glob("*/*.result.json")}
    if not groups:
        raise SystemExit(f"No inference result groups found in {pipeline_output_dir}")
    if "text" in groups:
        groups.remove("text")
        groups.update(("text_content", "text_formatting"))
    return sorted(groups)


def evaluate_group(group: str, report_dir: Path) -> None:
    parse_bench(
        "evaluation",
        "run",
        "--output_dir",
        str(Path(env("OUTPUT_DIR")) / env("PIPELINE")),
        "--test_cases_dir",
        env("DATA_DIR"),
        "--group",
        group,
        "--report_dir",
        str(report_dir),
        "--export_csv=False",
        "--export_rule_csv=False",
        "--export_markdown=False",
        "--export_html=False",
    )


def evaluate() -> None:
    pipeline_output_dir = Path(env("OUTPUT_DIR")) / env("PIPELINE")
    group = env("GROUP")
    if group != "all":
        evaluate_group(group, pipeline_output_dir)
        return

    groups = evaluation_groups(pipeline_output_dir)
    (pipeline_output_dir / "_eval_groups.txt").write_text("\n".join(groups) + "\n", encoding="utf-8")
    for evaluation_group in groups:
        evaluate_group(evaluation_group, pipeline_output_dir / evaluation_group)


def regenerate(evaluation_dir: Path, report_dir: Path) -> None:
    pipeline_output_dir = Path(env("OUTPUT_DIR")) / env("PIPELINE")
    parse_bench(
        "evaluation",
        "regenerate_report",
        "--evaluation_dir",
        str(evaluation_dir),
        "--test_cases_dir",
        env("DATA_DIR"),
        "--output_dir",
        str(pipeline_output_dir),
        "--report_dir",
        str(report_dir),
    )


def report() -> None:
    output_dir = Path(env("OUTPUT_DIR"))
    pipeline = env("PIPELINE")
    pipeline_output_dir = output_dir / pipeline
    if env("GROUP") != "all":
        regenerate(pipeline_output_dir, pipeline_output_dir)
        return

    groups_file = pipeline_output_dir / "_eval_groups.txt"
    for group in groups_file.read_text(encoding="utf-8").splitlines():
        if group:
            regenerate(pipeline_output_dir / group, pipeline_output_dir / group)
    parse_bench(
        "analysis",
        "generate_dashboard",
        "--evaluation_dir",
        str(pipeline_output_dir),
        "--pipeline_name",
        pipeline,
    )
    parse_bench("analysis", "generate_leaderboard", "--output_dir", str(output_dir))


COMMANDS = {
    "download": download,
    "inference": inference,
    "evaluate": evaluate,
    "report": report,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=COMMANDS)
    args = parser.parse_args()
    COMMANDS[args.command]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
