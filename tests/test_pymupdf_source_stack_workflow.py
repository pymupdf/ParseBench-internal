from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HELPERS = Path(__file__).parents[1] / ".github" / "scripts" / "pymupdf_source_stack"


def _load_module(name: str):
    sys.path.insert(0, str(HELPERS))
    try:
        path = HELPERS / f"{name}.py"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(HELPERS))


configure = _load_module("configure")
benchmark = _load_module("benchmark")
resolve_dataset = _load_module("resolve_dataset")
results_summary = _load_module("write_results_summary")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.28.0", "1.28.0"),
        ("feature/layout@next", "feature-layout-next"),
        ("a" * 60, "a" * 48),
    ],
)
def test_safe_ref_produces_bounded_path_component(value: str, expected: str) -> None:
    assert configure.safe_ref(value) == expected


def test_configure_maps_friendly_inputs_and_records_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    github_output = tmp_path / "github-output"
    values = {
        "BENCHMARK_REF": "main",
        "GCS_PREFIX": "/parsebench/pymupdf_source_stack/",
        "GITHUB_OUTPUT": str(github_output),
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_RUN_ID": "123",
        "GROUP_SELECTION": "Page layout",
        "PYMUPDF4LLM_REF": "feature/llm",
        "PYMUPDF_LAYOUT_REF": "1.28.0",
        "PYMUPDF_REF": "main",
        "RUNNER_TEMP": str(tmp_path),
        "RUN_SCOPE_SELECTION": "Quick test (15 cases)",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    assert configure.main() == 0

    outputs = dict(line.split("=", 1) for line in github_output.read_text().splitlines())
    assert outputs["run_scope"] == "test"
    assert outputs["data_dir"] == "data/test"
    assert outputs["group"] == "layout"
    assert outputs["artifact_name"] == "pymupdf-source-stack-123-2"
    assert "4llm-feature-llm" in outputs["destination"]

    request = json.loads((tmp_path / "parsebench-output" / "_source_request.json").read_text())
    assert request["pymupdf"] == {"ref": "main", "repository": "pymupdf/PyMuPDF"}
    assert request["pymupdf_layout"]["repository"] == "ArtifexSoftware/sce"


def test_evaluation_groups_expands_text_categories(tmp_path: Path) -> None:
    for group in ("chart", "text"):
        group_dir = tmp_path / group
        group_dir.mkdir()
        (group_dir / "case.result.json").touch()

    assert benchmark.evaluation_groups(tmp_path) == ["chart", "text_content", "text_formatting"]


def test_evaluation_groups_rejects_missing_inference_results(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="No inference result groups found"):
        benchmark.evaluation_groups(tmp_path)


@pytest.mark.parametrize(("scope", "branch"), [("full", "main"), ("test", "test-data")])
def test_dataset_branch_matches_run_scope(scope: str, branch: str) -> None:
    assert resolve_dataset.branch_for_scope(scope) == branch


def test_resolve_dataset_records_immutable_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    github_output = tmp_path / "github-output"
    output_dir = tmp_path / "output"
    sha = "a" * 40
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("DATASET_REF", "current")
    monkeypatch.setenv("OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("RUN_SCOPE", "test")
    monkeypatch.setattr(resolve_dataset, "resolve_branch", lambda repository, branch: sha)

    assert resolve_dataset.main() == 0

    outputs = dict(line.split("=", 1) for line in github_output.read_text().splitlines())
    assert outputs["branch"] == "test-data"
    assert outputs["sha"] == sha
    dataset = json.loads((output_dir / "_dataset.json").read_text())
    assert dataset["repository"] == "llamaindex/ParseBench"
    assert dataset["requested_ref"] == "current"
    assert dataset["resolved_sha"] == sha


def test_resolve_dataset_accepts_existing_full_commit_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    github_output = tmp_path / "github-output"
    sha = "d" * 40
    monkeypatch.setenv("DATASET_REF", sha.upper())
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("RUN_SCOPE", "full")
    monkeypatch.setattr(resolve_dataset, "validate_commit", lambda repository, revision: revision)
    monkeypatch.setattr(
        resolve_dataset,
        "resolve_branch",
        lambda repository, branch: pytest.fail("Explicit SHA must not resolve the current branch"),
    )

    assert resolve_dataset.main() == 0

    outputs = dict(line.split("=", 1) for line in github_output.read_text().splitlines())
    assert outputs["requested_ref"] == sha
    assert outputs["sha"] == sha


def test_resolve_dataset_rejects_ambiguous_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATASET_REF", "main")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github-output"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("RUN_SCOPE", "full")

    with pytest.raises(SystemExit, match="full 40-character commit SHA"):
        resolve_dataset.main()


def test_dataset_download_is_fresh_and_uses_exact_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import parse_bench.data.download

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "stale-file").write_text("old", encoding="utf-8")
    sha = "b" * 40
    call: dict[str, object] = {}

    def snapshot_download(**kwargs: object) -> None:
        assert not data_dir.exists()
        call.update(kwargs)
        data_dir.mkdir()

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=snapshot_download),
    )
    monkeypatch.setattr(parse_bench.data.download, "is_dataset_ready", lambda path: True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATASET_REPOSITORY", "llamaindex/ParseBench")
    monkeypatch.setenv("DATASET_SHA", sha)

    benchmark.download()

    assert call["revision"] == sha
    assert call["force_download"] is True
    marker = json.loads((data_dir / benchmark.DATASET_MARKER).read_text())
    assert marker == {
        "repository": "llamaindex/ParseBench",
        "resolved_sha": sha,
    }


def test_dataset_download_reuses_complete_matching_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import parse_bench.data.download

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sha = "c" * 40
    marker = {
        "repository": "llamaindex/ParseBench",
        "resolved_sha": sha,
    }
    (data_dir / benchmark.DATASET_MARKER).write_text(json.dumps(marker), encoding="utf-8")

    def unexpected_download(**kwargs: object) -> None:
        pytest.fail(f"Exact cached revision should be reused, got download arguments {kwargs}")

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=unexpected_download),
    )
    monkeypatch.setattr(parse_bench.data.download, "is_dataset_ready", lambda path: True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATASET_REPOSITORY", "llamaindex/ParseBench")
    monkeypatch.setenv("DATASET_SHA", sha)

    benchmark.download()

    assert data_dir.exists()


def _write_report(path: Path, *, total: int, metrics: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"total_examples": total, "aggregate_metrics": metrics}),
        encoding="utf-8",
    )


def test_results_summary_uses_dashboard_headline_metrics_and_overall_average(tmp_path: Path) -> None:
    _write_report(
        tmp_path / "table" / "_evaluation_report.json",
        total=3,
        metrics={"avg_grits_trm_composite": 0.6, "avg_rule_pass_rate": 0.9},
    )
    _write_report(
        tmp_path / "text_content" / "_evaluation_report.json",
        total=4,
        metrics={"avg_content_faithfulness": 0.8, "avg_rule_pass_rate_judge": 1.0},
    )

    scores = results_summary.load_scores(tmp_path, "all")
    markdown, data = results_summary.build_summary(scores)

    assert data["overall_score"] == pytest.approx(0.7)
    assert "Overall aggregate score: **70.0%**" in markdown
    assert "| Table | GriTS table score | 60.0% | 3 |" in markdown
    assert "| Text Content | Content faithfulness | 80.0% | 4 |" in markdown


def test_results_summary_supports_single_category_report(tmp_path: Path) -> None:
    _write_report(
        tmp_path / "_evaluation_report.json",
        total=2,
        metrics={"avg_layout_element_rule_pass_rate": 0.75},
    )

    scores = results_summary.load_scores(tmp_path, "layout")

    assert scores == [results_summary.CategoryScore("layout", "layout_element_rule_pass_rate", 0.75, 2)]


def test_results_summary_falls_back_to_rule_pass_rate(tmp_path: Path) -> None:
    _write_report(
        tmp_path / "chart" / "_evaluation_report.json",
        total=1,
        metrics={"avg_rule_pass_rate": 0.25, "avg_rule_pass_rate_judge": 0.5},
    )

    scores = results_summary.load_scores(tmp_path, "all")

    assert scores[0].metric == "rule_pass_rate"
    assert scores[0].score == 0.25
