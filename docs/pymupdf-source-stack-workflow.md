# PyMuPDF source-stack workflow

The `PyMuPDF Source Stack ParseBench` workflow benchmarks a selected Git ref
from each component of the PyMuPDF parsing stack without changing the pinned
`PyMuPDF4LLM ParseBench` workflow.

Each `*_ref` input accepts a branch, tag, or full commit SHA. The repository
inputs default to the upstream repositories known to ParseBench. Prefer full
commit SHAs for reproducible benchmark runs.

## Private repository access

PyMuPDF Layout source is currently read from the private
`ArtifexSoftware/sce` repository. Add a repository secret named
`PYMUPDF_SOURCE_TOKEN` containing a fine-grained token with read-only access to
the selected private source repositories. Public source checkouts fall back to
the workflow's standard GitHub token.

The `ArtifexSoftware/sce` `master` branch removed the installable runtime
package on 2026-07-10. The workflow therefore defaults to the last buildable
commit inspected by ParseBench:

```text
bc9127e72de0f4d75935a4ef51d141e928dd7943
```

Update the Layout repository input when the replacement runtime repository is
available to the ParseBench workflow token.

## Compatibility gate

The workflow builds and installs source packages in this order:

1. PyMuPDF
2. PyMuPDF Layout, linked against the selected PyMuPDF build
3. PyMuPDF4LLM, using the selected PyMuPDF and Layout builds

Before downloading the ParseBench dataset, the compatibility gate activates
Layout, creates a small PDF, calls PyMuPDF4LLM with the same page-chunk and OCR
DPI option shape used by the benchmark pipeline, and verifies that the result
contains both the marker text and non-empty Layout page boxes.

An incompatible stack fails before benchmark inference and writes diagnostic
details to `_compatibility.json` in the GitHub artifact. Successful runs also
record all requested refs, resolved commit SHAs, and installed distribution
versions in `_github_run.json`.

## Output security

Source code runs only in the benchmark job, which has no GCP credentials. A
separate publish job downloads the resulting GitHub artifact and uploads it to
GCS when `publish_to_gcs` is enabled. This prevents a selected source revision
from executing in the credentialed publishing job.
