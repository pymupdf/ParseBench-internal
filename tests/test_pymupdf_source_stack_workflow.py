from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

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
resolve_layout_source = _load_module("resolve_layout_source")
resolve_latest_branches = _load_module("resolve_latest_branches")
results_summary = _load_module("write_results_summary")
run_summary = _load_module("write_run_summary")


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
        "ALL_LATEST": "false",
        "BENCHMARK_REF": "main",
        "DATASET_REF": "current",
        "GCS_PREFIX": "/parsebench/pymupdf_source_stack/",
        "GITHUB_OUTPUT": str(github_output),
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_RUN_ID": "123",
        "GROUP_SELECTION": "Page layout",
        "LATEST_ANY_BRANCH": "false",
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
    assert outputs["all_latest"] == "false"
    assert outputs["pymupdf4llm_ref"] == "feature/llm"

    request = json.loads((tmp_path / "parsebench-output" / "_source_request.json").read_text())
    assert request["pymupdf"] == {"ref": "main", "repository": "pymupdf/PyMuPDF"}
    assert request["pymupdf_layout"] == {
        "ref": "1.28.0",
        "repositories": ["ArtifexSoftware/sce", "ArtifexSoftware/pymupdf_layout"],
    }


def test_configure_all_latest_overrides_source_inputs_but_preserves_dataset_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github_output = tmp_path / "github-output"
    values = {
        "ALL_LATEST": "true",
        "BENCHMARK_REF": "main",
        "DATASET_REF": "d" * 40,
        "GCS_PREFIX": "parsebench/pymupdf_source_stack",
        "GITHUB_OUTPUT": str(github_output),
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "456",
        "GROUP_SELECTION": "All categories",
        "LATEST_ANY_BRANCH": "false",
        "PYMUPDF4LLM_REF": "1.28.0",
        "PYMUPDF_LAYOUT_REF": "1.28.0",
        "PYMUPDF_REF": "a" * 40,
        "RUNNER_TEMP": str(tmp_path),
        "RUN_SCOPE_SELECTION": "Quick test (15 cases)",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    assert configure.main() == 0

    outputs = dict(line.split("=", 1) for line in github_output.read_text().splitlines())
    assert outputs["all_latest"] == "true"
    assert outputs["dataset_ref"] == "d" * 40
    assert outputs["pymupdf_ref"] == "main"
    assert outputs["pymupdf_layout_ref"] == "main"
    assert outputs["pymupdf4llm_ref"] == "main"

    request = json.loads((tmp_path / "parsebench-output" / "_source_request.json").read_text())
    assert request["pymupdf"] == {"ref": "main", "repository": "pymupdf/PyMuPDF"}


def test_configure_latest_any_branch_uses_resolver_placeholders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github_output = tmp_path / "github-output"
    values = {
        "ALL_LATEST": "false",
        "BENCHMARK_REF": "main",
        "DATASET_REF": "current",
        "GCS_PREFIX": "parsebench/pymupdf_source_stack",
        "GITHUB_OUTPUT": str(github_output),
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "789",
        "GROUP_SELECTION": "All categories",
        "LATEST_ANY_BRANCH": "true",
        "PYMUPDF4LLM_REF": "1.28.0",
        "PYMUPDF_LAYOUT_REF": "1.28.0",
        "PYMUPDF_REF": "1.28.0",
        "RUNNER_TEMP": str(tmp_path),
        "RUN_SCOPE_SELECTION": "Quick test (15 cases)",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    assert configure.main() == 0

    outputs = dict(line.split("=", 1) for line in github_output.read_text().splitlines())
    assert outputs["latest_any_branch"] == "true"
    assert outputs["pymupdf_ref"] == "latest-any-branch"
    assert "pymupdf-latest-any-branch" in outputs["destination"]


def test_configure_rejects_both_automatic_latest_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALL_LATEST", "true")
    monkeypatch.setenv("LATEST_ANY_BRANCH", "true")
    monkeypatch.setenv("BENCHMARK_REF", "main")
    monkeypatch.setenv("GROUP_SELECTION", "All categories")
    monkeypatch.setenv("RUN_SCOPE_SELECTION", "Quick test (15 cases)")

    with pytest.raises(SystemExit, match="not both"):
        configure.main()


def test_parse_branch_heads_selects_newest_commit_with_deterministic_tie() -> None:
    output = "\n".join(
        [
            f"main\t{'a' * 40}\t100",
            f"feature/older\t{'b' * 40}\t99",
            f"feature/newest\t{'c' * 40}\t101",
            f"feature/z-tie\t{'d' * 40}\t101",
        ]
    )

    assert resolve_latest_branches.parse_branch_heads(output, "owner/repo") == (
        resolve_latest_branches.BranchHead("feature/z-tie", "d" * 40, 101)
    )


def test_resolve_latest_branches_records_pinned_shas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github_output = tmp_path / "github-output"
    output_dir = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("OUTPUT_DIR", str(output_dir))

    heads = {
        "pymupdf/PyMuPDF": resolve_latest_branches.BranchHead("feature/core", "a" * 40, 10),
        "ArtifexSoftware/pymupdf_layout": resolve_latest_branches.BranchHead(
            "feature/layout", "b" * 40, 20
        ),
        "pymupdf/pymupdf4llm": resolve_latest_branches.BranchHead("feature/llm", "c" * 40, 30),
    }
    monkeypatch.setattr(
        resolve_latest_branches,
        "latest_branch_head",
        lambda repository, token: heads[repository],
    )

    assert resolve_latest_branches.main() == 0

    outputs = dict(line.split("=", 1) for line in github_output.read_text().splitlines())
    assert outputs["pymupdf_branch"] == "feature/core"
    assert outputs["pymupdf_sha"] == "a" * 40
    assert outputs["pymupdf_layout_repository"] == "ArtifexSoftware/pymupdf_layout"
    request = json.loads((output_dir / "_source_request.json").read_text())
    assert request["pymupdf4llm"]["branch"] == "feature/llm"
    assert request["pymupdf4llm"]["resolved_sha"] == "c" * 40


def _layout_resolution_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    github_output = tmp_path / "github-output"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "_source_request.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("PREFER_CURRENT_REPOSITORY", "false")
    monkeypatch.setenv("PYMUPDF_LAYOUT_REF", "main")
    return output_dir


def test_layout_resolution_prefers_legacy_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = _layout_resolution_environment(tmp_path, monkeypatch)
    sha = "a" * 40
    calls: list[str] = []

    def resolve(repository: str, requested_ref: str, token: str) -> str | None:
        calls.append(repository)
        assert requested_ref == "main"
        assert token == "test-token"
        return sha

    monkeypatch.setattr(resolve_layout_source, "resolve_commit", resolve)

    assert resolve_layout_source.main() == 0
    assert calls == ["ArtifexSoftware/sce"]
    request = json.loads((output_dir / "_source_request.json").read_text())
    assert request["pymupdf_layout"] == {
        "ref": "main",
        "repository": "ArtifexSoftware/sce",
        "resolved_sha": sha,
    }


def test_layout_resolution_falls_back_to_current_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = _layout_resolution_environment(tmp_path, monkeypatch)
    sha = "b" * 40

    def resolve(repository: str, requested_ref: str, token: str) -> str | None:
        return sha if repository == "ArtifexSoftware/pymupdf_layout" else None

    monkeypatch.setattr(resolve_layout_source, "resolve_commit", resolve)

    assert resolve_layout_source.main() == 0
    source = json.loads((output_dir / "_layout_source.json").read_text())
    assert source == {
        "repository": "ArtifexSoftware/pymupdf_layout",
        "requested_ref": "main",
        "resolved_sha": sha,
    }


def test_layout_resolution_all_latest_prefers_current_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = _layout_resolution_environment(tmp_path, monkeypatch)
    sha = "c" * 40
    calls: list[str] = []
    monkeypatch.setenv("PREFER_CURRENT_REPOSITORY", "true")

    def resolve(repository: str, requested_ref: str, token: str) -> str | None:
        calls.append(repository)
        return sha

    monkeypatch.setattr(resolve_layout_source, "resolve_commit", resolve)

    assert resolve_layout_source.main() == 0
    assert calls == ["ArtifexSoftware/pymupdf_layout"]
    source = json.loads((output_dir / "_layout_source.json").read_text())
    assert source["repository"] == "ArtifexSoftware/pymupdf_layout"


def test_layout_resolution_treats_unprocessable_ref_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unprocessable(*args: object, **kwargs: object) -> None:
        raise HTTPError("https://api.github.com", 422, "No commit found", None, None)

    monkeypatch.setattr(resolve_layout_source, "urlopen", unprocessable)

    assert resolve_layout_source.resolve_commit("ArtifexSoftware/sce", "a" * 40, "token") is None


def test_layout_resolution_reports_missing_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = _layout_resolution_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(resolve_layout_source, "resolve_commit", lambda repository, ref, token: None)

    with pytest.raises(SystemExit, match="was not found"):
        resolve_layout_source.main()

    failure = json.loads((output_dir / "_failure.json").read_text())
    assert failure["title"] == "Cannot resolve PyMuPDF Layout source"


def test_layout_resolution_records_github_service_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = _layout_resolution_environment(tmp_path, monkeypatch)

    def unavailable(repository: str, ref: str, token: str) -> None:
        raise SystemExit(f"GitHub rejected {repository}@{ref}: HTTP 503")

    monkeypatch.setattr(resolve_layout_source, "resolve_commit", unavailable)

    with pytest.raises(SystemExit, match="retry this workflow later"):
        resolve_layout_source.main()

    failure = json.loads((output_dir / "_failure.json").read_text())
    assert failure["title"] == "GitHub API temporarily unavailable"
    assert failure["http_status"] == 503
    assert failure["repository"] == "ArtifexSoftware/sce"
    assert failure["requested_ref"] == "main"
    assert "not a PyMuPDF source compatibility failure" in failure["error"]
    assert "benchmark execution were skipped" in failure["details"]


def _source_revisions(commits_after: int | None) -> list[run_summary.SourceRevision]:
    return [
        run_summary.SourceRevision(
            label="PyMuPDF",
            repository="pymupdf/PyMuPDF",
            requested_ref="1.28.0",
            sha="a" * 40,
            commit_date="2026-07-19 12:34:56 UTC",
            commits_after=commits_after,
        )
    ]


def test_versioned_source_summary_uses_readable_clickable_commit_distance() -> None:
    markdown = "\n".join(run_summary.source_table(_source_revisions(7), all_latest=False))

    assert "[7 commits ago](https://github.com/pymupdf/PyMuPDF/commit/" + "a" * 40 + ")" in markdown
    assert "2026-07-19 12:34:56 UTC" in markdown
    assert "Exact commit used" not in markdown


def test_all_latest_source_summary_shows_dates_without_comparison_count() -> None:
    markdown = "\n".join(run_summary.source_table(_source_revisions(None), all_latest=True))

    assert "Latest commits were requested for all three PyMuPDF repositories." in markdown
    assert "[Latest commit](https://github.com/pymupdf/PyMuPDF/commit/" + "a" * 40 + ")" in markdown
    assert "2026-07-19 12:34:56 UTC" in markdown


def test_latest_any_branch_summary_shows_selected_branch_and_pinned_commit() -> None:
    revisions = [
        run_summary.SourceRevision(
            label="PyMuPDF",
            repository="pymupdf/PyMuPDF",
            requested_ref="feature/new-parser",
            sha="a" * 40,
            commit_date="2026-07-19 12:34:56 UTC",
            commits_after=None,
        )
    ]

    markdown = "\n".join(run_summary.source_table(revisions, False, True))

    assert "newest branch-head commit" in markdown
    assert "`feature/new-parser`" in markdown
    assert "[Latest branch-head commit](https://github.com/pymupdf/PyMuPDF/commit/" in markdown


@pytest.mark.parametrize(
    ("commits_after", "label"),
    [(0, "Latest commit"), (1, "1 commit ago"), (4, "4 commits ago"), (None, "Selected commit")],
)
def test_commit_label_is_human_readable(commits_after: int | None, label: str) -> None:
    assert run_summary.commit_label(commits_after) == label


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
