#!/usr/bin/env python3
"""Render headline ParseBench scores directly in the GitHub run summary."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

from common import append_summary, env, write_json

# Keep this aligned with parse_bench.analysis.aggregation_report._DEFAULT_METRICS.
DEFAULT_METRICS = {
    "table": "grits_trm_composite",
    "layout": "layout_element_rule_pass_rate",
    "text_content": "content_faithfulness",
    "text_formatting": "semantic_formatting",
    "form": "rule_form_field_pass_rate",
}


@dataclass(frozen=True)
class CategoryScore:
    category: str
    metric: str | None
    score: float | None
    evaluated_cases: int


def display_name(value: str) -> str:
    special_names = {
        "grits_trm_composite": "GriTS table score",
        "layout_element_rule_pass_rate": "Layout element pass rate",
        "content_faithfulness": "Content faithfulness",
        "semantic_formatting": "Semantic formatting",
        "rule_form_field_pass_rate": "Form field pass rate",
        "rule_pass_rate": "Rule pass rate",
    }
    return special_names.get(value, value.replace("_", " ").title())


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def category_score(category: str, report: dict[str, Any]) -> CategoryScore:
    aggregate_metrics = report.get("aggregate_metrics", {})
    metrics = {
        key.removeprefix("avg_"): value
        for key, raw_value in aggregate_metrics.items()
        if key.startswith("avg_")
        and "_predicted" not in key
        and "_judge" not in key
        and (value := _numeric(raw_value)) is not None
    }

    metric = DEFAULT_METRICS.get(category, "rule_pass_rate")
    if metric not in metrics:
        metric = "rule_pass_rate" if "rule_pass_rate" in metrics else next(iter(sorted(metrics)), None)
    score = metrics.get(metric) if metric is not None else None
    total_examples = report.get("total_examples", 0)
    evaluated_cases = total_examples if isinstance(total_examples, int) and total_examples >= 0 else 0
    return CategoryScore(category, metric, score, evaluated_cases)


def discover_reports(pipeline_output_dir: Path, selected_group: str) -> list[tuple[str, Path]]:
    category_reports = [
        (path.parent.name, path)
        for path in sorted(pipeline_output_dir.glob("*/_evaluation_report.json"))
    ]
    if category_reports:
        return category_reports

    report = pipeline_output_dir / "_evaluation_report.json"
    if report.is_file():
        return [(selected_group, report)]
    raise FileNotFoundError(f"No evaluation reports found in {pipeline_output_dir}")


def load_scores(pipeline_output_dir: Path, selected_group: str) -> list[CategoryScore]:
    scores = []
    for category, path in discover_reports(pipeline_output_dir, selected_group):
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError(f"Expected a JSON object in {path}")
        scores.append(category_score(category, report))
    return scores


def build_summary(scores: list[CategoryScore]) -> tuple[str, dict[str, Any]]:
    available_scores = [category.score for category in scores if category.score is not None]
    overall = fmean(available_scores) if available_scores else None
    overall_display = f"**{overall:.1%}**" if overall is not None else "**N/A**"
    lines = [
        "## Aggregate benchmark results",
        "",
        f"Overall aggregate score: {overall_display}",
        "",
        "The overall score is the unweighted average of the headline metric shown for each category.",
        "",
        "| Category | Headline metric | Aggregate score | Evaluated cases |",
        "| --- | --- | ---: | ---: |",
    ]
    for category in scores:
        score = f"{category.score:.1%}" if category.score is not None else "N/A"
        metric = display_name(category.metric) if category.metric else "No aggregate metric available"
        lines.append(
            f"| {display_name(category.category)} | {metric} | {score} | {category.evaluated_cases} |"
        )
    lines.append("")
    data = {
        "overall_score": overall,
        "overall_method": "unweighted_average_of_category_headline_metrics",
        "categories": [asdict(category) for category in scores],
    }
    return "\n".join(lines), data


def main() -> int:
    output_dir = Path(env("OUTPUT_DIR"))
    pipeline_output_dir = output_dir / env("PIPELINE")
    scores = load_scores(pipeline_output_dir, env("GROUP"))
    markdown, data = build_summary(scores)
    write_json(output_dir / "_benchmark_scores.json", data)
    append_summary(markdown.rstrip().splitlines())
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
