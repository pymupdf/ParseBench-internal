# Repository Agent Instructions

## PyMuPDF concurrency

- Always run `pymupdf4llm` pipelines with `--max_concurrent 1`.
- ParseBench uses a thread pool when inference concurrency is greater than one, and PyMuPDF does not support multithreaded use. Concurrent threads may return incorrect results or crash Python.
- Do not increase concurrency for these pipelines unless inference is moved to isolated processes and every process opens its own document.
- This is a thread-safety restriction, not a claim that PyMuPDF is generally memory-unsafe.
