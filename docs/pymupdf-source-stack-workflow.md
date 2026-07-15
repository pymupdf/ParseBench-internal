# ParseBench Version Lab

The `ParseBench Version Lab` workflow benchmarks a selected Git ref
from each component of the PyMuPDF parsing stack without changing the pinned
`PyMuPDF4LLM ParseBench` workflow.

The manual form keeps the repositories fixed and asks only for the ParseBench
ref, three component refs, dataset size, and document category. Each component
ref accepts a release tag, branch, or full commit SHA. Leave the displayed
defaults unchanged for a standard quick test; prefer full commit SHAs for
reproducible benchmark runs.

Enter only the Git ref, not a GitHub URL. Examples:

- Version tag: `1.28.0`
- Branch: `main`
- Commit: `e9cdfc9e7fe3260efcc9d28713903f075ab05bce` (the full 40-character SHA)

The fixed source repositories are:

- PyMuPDF: `pymupdf/PyMuPDF`
- PyMuPDF Layout: `ArtifexSoftware/sce`
- PyMuPDF4LLM: `pymupdf/pymupdf4llm`

Every run starts its GitHub summary with the selected dataset size, document
category, pipeline, and source configuration. For ParseBench and all three
components, the summary shows both the branch, tag, or SHA entered by the user
and the exact 40-character commit checked out for that run.

## Private repository access

PyMuPDF Layout source is currently read from the private
`ArtifexSoftware/sce` repository. Add a repository secret named
`PYMUPDF_SOURCE_TOKEN` containing a fine-grained token with read-only access to
the selected private source repositories. Public source checkouts fall back to
the workflow's standard GitHub token.

PyMuPDF Layout uses Git tags even though the private repository does not publish
entries on GitHub's Releases page. The workflow defaults to the human-readable
`1.28.0` tag, which resolves to:

```text
2e21fab5bb27e0296cc54c6d73eeb774402553db
```

The `ArtifexSoftware/sce` `master` branch removed the installable runtime
package on 2026-07-10, so `master` is not currently a suitable Layout source
selection. Update the fixed Layout repository in the workflow when the
replacement runtime repository is available to the ParseBench workflow token.

## MuPDF version

MuPDF is the native engine wrapped by PyMuPDF, not a separately installed
Python dependency. Each PyMuPDF source revision defines the MuPDF source
release it requires. When this workflow builds the selected PyMuPDF revision,
PyMuPDF automatically downloads and compiles that matching MuPDF source. For
example, PyMuPDF `1.28.0` selects MuPDF `1.28.0`.

PyMuPDF has an advanced build override for selecting a different MuPDF source,
but ParseBench intentionally does not expose it. Allowing the native engine and
its Python wrapper to vary independently would create unsupported combinations
that can fail while compiling PyMuPDF, before the source-stack compatibility
gate. Selecting the PyMuPDF ref therefore selects the corresponding MuPDF
version automatically.

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

If benchmarking or publishing fails, a final `Explain workflow failure` job
adds the failed job and step names to the GitHub run summary. It includes the
complete compatibility traceback when available; for other failures, it
extracts the exception or relevant error context from the completed job log.

## Output security

Source code runs only in the benchmark job, which has no GCP credentials. A
separate publish job downloads the resulting GitHub artifact and uploads it to
the fixed ParseBench GCS location. Partial diagnostic output is also published
when compatibility or benchmarking fails. This prevents a selected source
revision from executing in the credentialed publishing job.

The publishing node is named `Publish benchmark results` after a successful
benchmark. After a failure, the same secured publishing path is instead named
`Publish failure diagnostics`, and its summary explicitly states that no
completed benchmark results were published.
