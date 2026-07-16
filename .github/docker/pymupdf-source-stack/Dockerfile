# syntax=docker/dockerfile:1.7

FROM python:3.12.13-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS python-runtime

FROM ubuntu:24.04@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90

ARG UBUNTU_SNAPSHOT=20260716T205900Z
ARG UV_VERSION=0.11.29

LABEL org.opencontainers.image.source="https://github.com/pymupdf/ParseBench-internal"
LABEL org.opencontainers.image.description="Reproducible native build and benchmark environment for the ParseBench PyMuPDF source stack"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONUNBUFFERED=1 \
    TZ=Etc/UTC

# The minimal Ubuntu base does not include a CA bundle. Bootstrap it from the
# digest-pinned Python stage so APT can verify snapshot.ubuntu.com, then replace
# it with Ubuntu's snapshot-pinned ca-certificates package below.
COPY --from=python-runtime /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt

# Freeze Ubuntu packages to the archive state used by the reference workflow
# run. The explicitly versioned OCR and build packages are the versions that
# run 29534227627 installed; all transitive packages come from the same archive
# snapshot.
RUN sed -i "/^URIs:/a Snapshot: ${UBUNTU_SNAPSHOT}" /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential=12.10ubuntu1 \
        ca-certificates \
        curl \
        file \
        git \
        libbz2-1.0 \
        libexpat1 \
        libffi8 \
        libgdbm-compat4t64 \
        libgdbm6t64 \
        libgif7=5.2.2-1ubuntu1 \
        libgomp1 \
        liblept5=1.82.0-3build4 \
        liblzma5 \
        libncursesw6 \
        libreadline8t64 \
        libsqlite3-0 \
        libssl3t64 \
        libtesseract5=5.3.4-1build5 \
        libuuid1 \
        locales \
        pkg-config \
        swig=4.2.0-2ubuntu1 \
        tesseract-ocr=5.3.4-1build5 \
        tesseract-ocr-eng=1:4.1.0-2 \
        tesseract-ocr-osd=1:4.1.0-2 \
        tzdata \
        zlib1g \
        zstd \
    && rm -rf /var/lib/apt/lists/*

# setup-python selected CPython 3.12.13 in the reference run. Copy the exact
# official CPython userspace from its digest-pinned image while retaining the
# Ubuntu 24.04 native libraries and compiler toolchain above.
COPY --from=python-runtime /usr/local/ /usr/local/

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && python --version \
    && uv --version \
    && swig -version \
    && tesseract --version \
    && tesseract --list-langs | grep -Fx eng

RUN mkdir -p /usr/local/share/parsebench \
    && printf '%s\n' \
        "ubuntu_snapshot=${UBUNTU_SNAPSHOT}" \
        "python=3.12.13" \
        "uv=${UV_VERSION}" \
        "build_essential=12.10ubuntu1" \
        "swig=4.2.0-2ubuntu1" \
        "tesseract=5.3.4-1build5" \
        "tesseract_eng=1:4.1.0-2" \
        "tesseract_osd=1:4.1.0-2" \
        "leptonica=1.82.0-3build4" \
        > /usr/local/share/parsebench/environment.txt

WORKDIR /__w/ParseBench-internal/ParseBench-internal
