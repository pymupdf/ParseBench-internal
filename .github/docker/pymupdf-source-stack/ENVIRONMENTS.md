# ParseBench container environment inventory

This file inventories the container environment used by `ParseBench Version
Lab` and the earlier workflows that built and validated it. The adjacent
`Dockerfile` is the reproducible definition for rebuilding the environment.

## Registry

- Image repository: `ghcr.io/pymupdf/parsebench-source-stack-env`
- Platform: `linux/amd64`
- Dockerfile: `.github/docker/pymupdf-source-stack/Dockerfile`

Always use an immutable digest when reintroducing an image into the benchmark.
The run-specific tags are also immutable by convention; the date-based version
tag without `-r2` was overwritten by a later successful build.

## Published images

| Publisher run | Source commit | Tags | Immutable digest | Notes |
| --- | --- | --- | --- | --- |
| [29536412797](https://github.com/pymupdf/ParseBench-Version-Lab/actions/runs/29536412797) | `a26592adb64d6da01f7fdf22dfdbb5977b54cd96` | `run-29536412797-attempt-1`, initially `ubuntu24-python3.12.13-20260716` | `sha256:09dc41716541e62e3eb21b0b5ef23495fba6c921a62b8eda032990c6575add86` | First successfully published complete native Python environment. The date-based tag was later moved to the next image. |
| [29536709611](https://github.com/pymupdf/ParseBench-Version-Lab/actions/runs/29536709611) | `b5d501497ac00c0768b757c4b52559bc6358f4f1` | `run-29536709611-attempt-1`, `ubuntu24-python3.12.13-20260716` | `sha256:ffc187e250ab4a1f3f70f1487460eef9e54ca5d2e63f64f8cc4fd2f18a9b5696` | Added `zstd` for GitHub cache extraction. This was the first image used by the container benchmark workflow. |
| [29538267457](https://github.com/pymupdf/ParseBench-Version-Lab/actions/runs/29538267457) | `76584a7fb569fad25e162f878d73b2434d6223ea` | `run-29538267457-attempt-1`, `ubuntu24-python3.12.13-20260716-r2` | `sha256:be78034c9188ad341b8d02d34d1702e3d8a870c47dc65a261e3d972718d26601` | Added the native `libgl1` and `libglib2.0-0t64` libraries required by the pinned RapidOCR/OpenCV stack. This is the latest and recommended image. |

The first three publisher attempts failed before the publish step and therefore
did not create usable registry images.

## Reproducible environment definition

The latest image uses:

- Ubuntu `24.04` base image at
  `sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90`
- Ubuntu archive snapshot `20260716T205900Z`
- CPython `3.12.13` copied from `python:3.12.13-slim-bookworm` at
  `sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b`
- `uv==0.11.29`
- `build-essential=12.10ubuntu1`
- `swig=4.2.0-2ubuntu1`
- `tesseract-ocr=5.3.4-1build5`
- English and OSD Tesseract data `1:4.1.0-2`
- `liblept5=1.82.0-3build4`
- `libgl1=1.7.0-1build1`
- `libglib2.0-0t64=2.80.0-6ubuntu1`
- `zstd` for Actions cache archives

The image contains system and build dependencies, not the selected PyMuPDF
source stack or the ParseBench Python environment. The benchmark workflow still
needs to install its locked dependencies and build the selected PyMuPDF,
PyMuPDF Layout, and PyMuPDF4LLM revisions inside the container. In particular,
`rapidocr-onnxruntime==1.2.3` and `opencv-python==4.13.0.92` were installed only
inside the publisher's validation environment; they were not baked into the
image.

The image writes its principal versions to
`/usr/local/share/parsebench/environment.txt` for runtime verification.

## Previous benchmark validation

The recommended `r2` digest completed the full 15-case, all-category smoke path
successfully in these runs:

- [Run 29538603995](https://github.com/pymupdf/ParseBench-Version-Lab/actions/runs/29538603995)
- [Run 29539899461](https://github.com/pymupdf/ParseBench-Version-Lab/actions/runs/29539899461)

The second run used the then-latest PyMuPDF, PyMuPDF Layout from the new
`ArtifexSoftware/pymupdf_layout` repository, and PyMuPDF4LLM commits.

## Version Lab integration

The production workflow uses the following integration:

1. Reference the recommended image by its full `@sha256:...` digest.
2. Grant `packages: read` and provide `github.actor` / `github.token` as GHCR
   credentials if the package requires authentication.
3. Run workflow shell steps with Bash inside the container.
4. Mark the workspace and the three source checkouts as Git safe directories,
   because Actions mounts them with host ownership.
5. Use `uv sync --locked --extra runners`, excluding the three source-built
   PyMuPDF packages as the current workflow does.
6. Verify `/usr/local/share/parsebench/environment.txt`, Python, Tesseract,
   SWIG, and the RapidOCR import before compiling the selected source stack.
7. Keep the existing behavioral Layout/OCR compatibility test as the final
   environment and source-stack gate.
