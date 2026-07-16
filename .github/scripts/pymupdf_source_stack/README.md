# PyMuPDF source-stack workflow helpers

These scripts implement the executable parts of
`../../workflows/pymupdf-source-stack-parsebench.yml`. The workflow YAML is
kept as the orchestration layer: inputs, permissions, jobs, third-party actions,
and user-facing step names stay visible there. Branching, JSON generation,
source discovery, benchmark commands, publishing, and summary rendering live
here so they can be linted and tested as normal Python.

Successful runs read the generated `_evaluation_report.json` files and append
an overall aggregate plus category headline scores directly to the GitHub run
summary. `_benchmark_scores.json` records the same values in the uploaded
artifact.

Each script is a small command with one responsibility. `resolve_dataset.py`
resolves the selected Hugging Face branch to a full commit SHA, and
`benchmark.py download` reuses only a complete cached snapshot whose internal
revision marker matches that SHA. A missing, stale, or incomplete snapshot is
removed and downloaded again. Inputs supplied by the workflow are passed
through environment variables, while values needed by later steps are written
using the standard `GITHUB_OUTPUT` and `GITHUB_STEP_SUMMARY` files.

Run the local checks with:

```shell
uv run --extra dev ruff check .github/scripts/pymupdf_source_stack tests
uv run --extra dev pytest tests/test_pymupdf_source_stack_workflow.py tests/test_github_failure_summary.py
```
