#!/usr/bin/env python3
"""Run dataset, inference, evaluation, and reporting phases for the workflow."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from common import env

DATASET_MARKER = ".parsebench-dataset-revision.json"


def run(*arguments: str) -> None:
    subprocess.run(arguments, check=True)


def parse_bench(*arguments: str) -> None:
    run("uv", "run", "parse-bench", *arguments)


def download() -> None:
    from huggingface_hub import snapshot_download

    from parse_bench.data.download import is_dataset_ready

    data_dir = Path(env("DATA_DIR"))
    repository = env("DATASET_REPOSITORY")
    revision = env("DATASET_SHA")
    marker_path = data_dir / DATASET_MARKER
    expected_marker = {"repository": repository, "resolved_sha": revision}

    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        marker = None

    if marker == expected_marker and is_dataset_ready(data_dir):
        print(f"Reusing cached immutable dataset snapshot: {repository}@{revision}")
        return

    if data_dir.exists():
        print("Cached dataset is absent, incomplete, or for a different revision; downloading it again.")
        shutil.rmtree(data_dir)

    print(f"Downloading immutable dataset snapshot: {repository}@{revision}")
    snapshot_download(
        repo_id=repository,
        repo_type="dataset",
        local_dir=str(data_dir),
        revision=revision,
        force_download=True,
    )
    if not is_dataset_ready(data_dir):
        raise SystemExit(f"Dataset snapshot {repository}@{revision} is incomplete at {data_dir}")
    marker_path.write_text(json.dumps(expected_marker, indent=2) + "\n", encoding="utf-8")


def _mem_monitor() -> None:
    # Temporary forensics (run branch only): the parent process outlives the
    # inference subprocess, shares its cgroup, and its stdout reaches the step
    # log — so log container-wide memory and the biggest processes every 5s.
    import os
    import sys
    import time

    def cgroup_gb() -> float:
        for path in ("/sys/fs/cgroup/memory.current",
                     "/sys/fs/cgroup/memory/memory.usage_in_bytes"):
            try:
                with open(path, encoding="ascii") as f:
                    return int(f.read().strip()) / 1e9
            except (OSError, ValueError):
                continue
        return 0.0

    def top_procs(count: int = 3) -> list[tuple[float, str, str]]:
        procs = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                rss = 0
                with open(f"/proc/{pid}/status", encoding="ascii",
                          errors="ignore") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            rss = int(line.split()[1])
                            break
                if rss < 50_000:
                    continue
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read().replace(b"\0", b" ").decode("utf-8",
                                                               "ignore")[:80]
                procs.append((rss / 1e6, pid, cmd))
            except OSError:
                continue
        return sorted(procs, reverse=True)[:count]

    while True:
        tops = "; ".join(f"{gb:.2f}GB pid={pid} {cmd}"
                         for gb, pid, cmd in top_procs())
        print(f"[mem-watch] cgroup={cgroup_gb():.2f}GB | {tops}",
              file=sys.stderr, flush=True)
        time.sleep(5)


def inference() -> None:
    import threading

    threading.Thread(target=_mem_monitor, daemon=True).start()
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
