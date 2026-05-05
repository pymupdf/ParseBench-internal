"""Shared metric aggregation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

CountTriple = tuple[int, int, int]


def add_precision_recall_f1_aggregates(
    aggregate: dict[str, float],
    metric_counts: Mapping[str, Sequence[CountTriple]],
) -> None:
    """Add total TP/FP/FN and pooled micro precision/recall/F1 aggregates."""
    summed_counts: dict[str, CountTriple] = {}
    for metric_name, counts in metric_counts.items():
        tp = sum(item[0] for item in counts)
        fp = sum(item[1] for item in counts)
        fn = sum(item[2] for item in counts)
        summed_counts[metric_name] = (tp, fp, fn)
        aggregate[f"total_{metric_name}_tp"] = float(tp)
        aggregate[f"total_{metric_name}_fp"] = float(fp)
        aggregate[f"total_{metric_name}_fn"] = float(fn)

    for precision_metric, counts in summed_counts.items():
        if not precision_metric.endswith("_precision"):
            continue

        metric_prefix = precision_metric[: -len("_precision")]
        recall_metric = f"{metric_prefix}_recall"
        f1_metric = f"{metric_prefix}_f1"
        if recall_metric not in summed_counts or f1_metric not in summed_counts:
            continue

        tp, fp, fn = counts
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2.0 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        aggregate[f"micro_{precision_metric}"] = precision
        aggregate[f"micro_{recall_metric}"] = recall
        aggregate[f"micro_{f1_metric}"] = f1
