"""Upstream source version fetcher for loinc-ingest.

Implements `get_source_versions()` returning SourceVersion-shaped dicts
conforming to the kozahub-metadata-schema, consumed by `just metadata`.
"""

from __future__ import annotations

import csv
import gzip
import os
from pathlib import Path
from typing import Any

from kozahub_metadata_schema import now_iso, urls_from_download_yaml

INGEST_DIR = Path(__file__).resolve().parents[1]
DOWNLOAD_YAML = INGEST_DIR / "download.yaml"
LOINC_FILE = INGEST_DIR / "data" / "loinc.csv.gz"

# Tuva's headerless LOINC table column order; version_last_changed is the last column.
_VERSION_LAST_CHANGED_COL = 19


def _semver_key(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def _actual_loinc_version() -> str:
    """The real LOINC release version, derived from the downloaded table.

    The Tuva path is versioned by Tuva's *terminology* release (e.g. 0.16.0), not by the
    LOINC version. The authoritative LOINC version is the max `version_last_changed` across
    the table (e.g. 2.80). Returns 'unknown' if the file hasn't been downloaded yet.
    """
    if not LOINC_FILE.exists():
        return "unknown"
    versions = set()
    with gzip.open(LOINC_FILE, "rt") as fh:
        for row in csv.reader(fh):
            if len(row) > _VERSION_LAST_CHANGED_COL:
                versions.add(row[_VERSION_LAST_CHANGED_COL])
    return max(versions, key=_semver_key) if versions else "unknown"


def get_source_versions() -> list[dict[str, Any]]:
    """Two logical sources: the LOINC release table (nodes) and OMOP2OBO (all edges).

    LOINC nodes come from the Tuva Project's repackaged LOINC table (public S3), pinned to a
    Tuva terminology release via TUVA_TERMINOLOGY_VERSION. We report the *actual* LOINC
    version (derived from the table) and note the Tuva release that delivered it. OMOP2OBO is
    a fixed Zenodo snapshot built on LOINC 2.64 / Sept-2020 ontologies.
    """
    tuva_version = os.getenv("TUVA_TERMINOLOGY_VERSION", "0.16.0")
    loinc_url = urls_from_download_yaml(DOWNLOAD_YAML, contains=["tuva"])[0]
    loinc_url = loinc_url.replace("{TUVA_TERMINOLOGY_VERSION}", tuva_version)
    return [
        {
            "id": "infores:loinc",
            "name": f"LOINC release table (via Tuva terminology {tuva_version})",
            "urls": [loinc_url],
            "version": _actual_loinc_version(),  # actual LOINC release, e.g. 2.80
            "version_method": "loinc_table_max_version_last_changed",
            "retrieved_at": now_iso(),
        },
        {
            "id": "infores:omop2obo",
            "name": "OMOP2OBO Measurement Mappings",
            # Fetched by scripts/preprocess.py (not download.yaml — Zenodo 403s kghub's UA).
            "urls": ["https://doi.org/10.5281/zenodo.6949858"],
            "version": "V1.1",  # 2020-10-01
            "version_method": "static",
            "retrieved_at": now_iso(),
        },
        {
            "id": "infores:comploinc",
            "name": "CompLOINC (is_a hierarchy)",
            "urls": ["https://github.com/loinc/comp-loinc/releases/tag/v2022-12-05"],
            "version": "v2022-12-05",
            "version_method": "github_release",
            "retrieved_at": now_iso(),
            # The version weirdness, captured explicitly: this CompLOINC release was built on
            # a ~2022 LOINC (circa 2.73), while the node table above is LOINC 2.80 — so the
            # graph carries two LOINC vintages. Consequently the hierarchy is partial: only
            # ~10% of the 2.80 leaf codes receive an is_a parent in this release. Full coverage
            # would require building current CompLOINC from a current LOINC release.
            "notes": (
                "is_a hierarchy from CompLOINC v2022-12-05 (built on LOINC ~2.73); "
                "node table is LOINC 2.80. ~10% of leaf nodes get a parent in this release."
            ),
        },
    ]
