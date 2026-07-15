from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HELPERS = Path(__file__).parents[1] / ".github" / "scripts" / "pymupdf_source_stack"


def _load_module(name: str):
    sys.path.insert(0, str(HELPERS))
    try:
        path = HELPERS / f"{name}.py"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(HELPERS))


configure = _load_module("configure")
benchmark = _load_module("benchmark")


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
