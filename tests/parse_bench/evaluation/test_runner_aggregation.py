from __future__ import annotations

from pathlib import Path

import pytest

from parse_bench.evaluation.runner import EvaluationRunner
from parse_bench.schemas.evaluation import EvaluationResult, MetricValue


def test_runner_uses_avg_for_macro_and_micro_for_pooled_extract_metrics() -> None:
    runner = EvaluationRunner(output_dir=Path("/tmp/unused"))
    results = [
        EvaluationResult(
            test_id="a",
            example_id="a",
            pipeline_name="p",
            product_type="extract",
            success=True,
            metrics=[
                MetricValue(metric_name="extract_value_precision", value=0.5, metadata={"tp": 1, "fp": 1, "fn": 1}),
                MetricValue(metric_name="extract_value_recall", value=0.5, metadata={"tp": 1, "fp": 1, "fn": 1}),
                MetricValue(metric_name="extract_value_f1", value=0.5, metadata={"tp": 1, "fp": 1, "fn": 1}),
                MetricValue(
                    metric_name="extract_element_pass_rate",
                    value=0.5,
                    metadata={"passed": 1, "total": 2, "tp": 1, "fp": 1, "fn": 0},
                ),
                MetricValue(
                    metric_name="extract_bbox_iou",
                    value=0.25,
                    metadata={
                        "score_sum": 0.5,
                        "score_count": 2,
                        "intersection_area": 1.0,
                        "union_area": 4.0,
                    },
                ),
                MetricValue(
                    metric_name="extract_bbox_recall",
                    value=0.5,
                    metadata={
                        "score_sum": 1.0,
                        "score_count": 2,
                        "covered_gt_area": 2.0,
                        "gt_area": 4.0,
                    },
                ),
                MetricValue(
                    metric_name="parse_field_iou",
                    value=0.25,
                    metadata={
                        "score_sum": 0.5,
                        "score_count": 2,
                        "intersection_area": 100.0,
                        "union_area": 100.0,
                    },
                ),
                MetricValue(
                    metric_name="parse_field_bbox_recall",
                    value=0.5,
                    metadata={
                        "score_sum": 1.0,
                        "score_count": 2,
                        "covered_gt_area": 100.0,
                        "gt_area": 100.0,
                    },
                ),
                MetricValue(
                    metric_name="parse_field_text_similarity",
                    value=0.5,
                    metadata={"string_rule_count": 1, "total_rule_count": 2},
                ),
            ],
        ),
        EvaluationResult(
            test_id="b",
            example_id="b",
            pipeline_name="p",
            product_type="extract",
            success=True,
            metrics=[
                MetricValue(metric_name="extract_value_precision", value=1.0, metadata={"tp": 3, "fp": 0, "fn": 0}),
                MetricValue(metric_name="extract_value_recall", value=1.0, metadata={"tp": 3, "fp": 0, "fn": 0}),
                MetricValue(metric_name="extract_value_f1", value=1.0, metadata={"tp": 3, "fp": 0, "fn": 0}),
                MetricValue(
                    metric_name="extract_element_pass_rate",
                    value=1.0,
                    metadata={"passed": 3, "total": 3, "tp": 3, "fp": 0, "fn": 0},
                ),
                MetricValue(
                    metric_name="extract_bbox_iou",
                    value=1.0,
                    metadata={
                        "score_sum": 3.0,
                        "score_count": 3,
                        "intersection_area": 9.0,
                        "union_area": 9.0,
                    },
                ),
                MetricValue(
                    metric_name="extract_bbox_recall",
                    value=1.0,
                    metadata={
                        "score_sum": 3.0,
                        "score_count": 3,
                        "covered_gt_area": 3.0,
                        "gt_area": 3.0,
                    },
                ),
                MetricValue(
                    metric_name="parse_field_iou",
                    value=1.0,
                    metadata={
                        "score_sum": 3.0,
                        "score_count": 3,
                        "intersection_area": 0.0,
                        "union_area": 100.0,
                    },
                ),
                MetricValue(
                    metric_name="parse_field_bbox_recall",
                    value=1.0,
                    metadata={
                        "score_sum": 3.0,
                        "score_count": 3,
                        "covered_gt_area": 0.0,
                        "gt_area": 100.0,
                    },
                ),
                MetricValue(
                    metric_name="parse_field_text_similarity",
                    value=1.0,
                    metadata={"string_rule_count": 3, "total_rule_count": 3},
                ),
            ],
        ),
    ]

    aggregate = runner._aggregate_metrics(results)

    assert aggregate["avg_extract_value_f1"] == 0.75
    assert aggregate["micro_extract_value_precision"] == pytest.approx(0.8)
    assert aggregate["micro_extract_value_recall"] == pytest.approx(0.8)
    assert aggregate["micro_extract_value_f1"] == pytest.approx(0.8)
    assert aggregate["avg_extract_element_pass_rate"] == 0.75
    assert aggregate["micro_extract_element_pass_rate"] == pytest.approx(0.8)
    assert aggregate["avg_extract_bbox_iou"] == 0.625
    assert aggregate["micro_extract_bbox_iou"] == pytest.approx(3.5 / 5.0)
    assert aggregate["micro_extract_bbox_iou"] != pytest.approx(10.0 / 13.0)
    assert aggregate["avg_extract_bbox_recall"] == 0.75
    assert aggregate["micro_extract_bbox_recall"] == pytest.approx(4.0 / 5.0)
    assert aggregate["micro_extract_bbox_recall"] != pytest.approx(5.0 / 7.0)
    assert aggregate["avg_parse_field_iou"] == 0.625
    assert aggregate["micro_parse_field_iou"] == pytest.approx(3.5 / 5.0)
    assert aggregate["micro_parse_field_iou"] != pytest.approx(100.0 / 200.0)
    assert aggregate["avg_parse_field_bbox_recall"] == 0.75
    assert aggregate["micro_parse_field_bbox_recall"] == pytest.approx(4.0 / 5.0)
    assert aggregate["micro_parse_field_bbox_recall"] != pytest.approx(100.0 / 200.0)
    assert aggregate["avg_parse_field_text_similarity"] == 0.75
    assert aggregate["micro_parse_field_text_similarity"] == pytest.approx(0.875)
    assert "macro_extract_element_pass_rate" not in aggregate
