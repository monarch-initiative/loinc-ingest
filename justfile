# loinc-ingest justfile

# Package directory
PKG := "src"

# Explicitly enumerate transforms (add new ingests here)
TRANSFORMS := "nodes loinc_parts composition phenotype hierarchy"

# Tuva terminology release to pin the LOINC table download to (override to bump LOINC).
# 0.16.0 == LOINC 2.80. Set to 'latest' to track Tuva's current release.
TUVA_TERMINOLOGY_VERSION := env_var_or_default("TUVA_TERMINOLOGY_VERSION", "0.16.0")

# List all commands
_default:
    @just --list

# Initialize a new project
[group('project management')]
setup: _git-init install _git-add
    git commit -m "Initialize loinc-ingest"

# Install dependencies
[group('project management')]
install:
    uv sync --group dev

# Download source data
[group('ingest')]
download: install
    TUVA_TERMINOLOGY_VERSION={{TUVA_TERMINOLOGY_VERSION}} uv run downloader download.yaml

# Flatten the multi-sheet OMOP2OBO xlsx into tidy KGX-ready TSVs (koza can't read xlsx)
[group('ingest')]
prep: download
    uv run python scripts/preprocess.py

# Run all transforms
[group('ingest')]
transform-all: prep
    #!/usr/bin/env bash
    set -euo pipefail
    for t in {{TRANSFORMS}}; do
        if [ -n "$t" ]; then
            echo "Transforming $t..."
            uv run koza transform {{PKG}}/$t.yaml
        fi
    done

# Emit output/release-metadata.yaml describing this build's upstream sources and artifacts
[group('ingest')]
metadata:
    uv run python scripts/write_metadata.py

# Run full pipeline: install, download, transform, metadata, test
[group('ingest')]
run: test transform-all metadata

# Run specific transform
[group('ingest')]
transform NAME:
    uv run koza transform {{PKG}}/{{NAME}}.yaml

# Run tests
[group('development')]
test: install
    uv run pytest

# Run tests with coverage
[group('development')]
test-cov: install
    uv run pytest --cov=. --cov-report=term-missing

# Lint code
[group('development')]
lint:
    uv run ruff check .

# Format code
[group('development')]
format:
    uv run ruff format .

# Clean output directory
[group('ingest')]
clean:
    rm -rf output/

# Hidden recipes
_git-init:
    git init

_git-add:
    git add .
