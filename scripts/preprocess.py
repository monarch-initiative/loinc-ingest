"""Flatten the upstream sources into tidy KGX-ready TSVs for the koza transforms.

  data/omop2obo_meas.xlsx  ->  data/loinc_composition_edges.tsv   (ChEBI/UBERON/CL/PR/NCBITaxon)   [DuckDB]
                               data/loinc_phenotype_edges.tsv      (HPO, outcome-qualified)         [DuckDB]
  data/comploinc.owl       ->  data/loinc_hierarchy_edges.tsv      (is_a)                            [rdflib]
                               data/loinc_part_nodes.tsv           (LP Part / CC grouper nodes)      [rdflib]

Leaf-code nodes come from the LOINC release table (`data/loinc.csv.gz`) read directly by
the `nodes` koza transform.

This is also the pipeline's filtering stage. The koza transforms are deliberately
1-row-in/1-object-out, so every decision to *drop* a row lives in the FILTERS tuples
below — one named predicate per rule, all of which must hold for a row to survive.

Every edge's subject is resolved through the integer OMOP `CONCEPT_ID`, never the mapping
sheets' `CONCEPT_CODE`: Excel stored date-like LOINC codes (e.g. 2731-8) as dates in those
sheets, so the code is only reliable in the OMOP_CONCEPT_INFORMATION sheet, joined by id.

Source: https://zenodo.org/records/6949858  (OMOP2OBO Measurement Mappings, V1.1, MIT)
"""

import csv
import re
import urllib.request
from pathlib import Path

import duckdb
import rdflib

DATA = Path(__file__).resolve().parent.parent / "data"
XLSX = str(DATA / "omop2obo_meas.xlsx")
OWL = DATA / "comploinc.owl"

# OMOP2OBO is fetched here rather than via kghub-downloader: kghub hardcodes a
# `User-Agent: Mozilla/5.0`, which Zenodo blocks (403). A default urllib UA is allowed.
OMOP2OBO_URL = (
    "https://zenodo.org/api/records/6949858/files/"
    "OMOP2OBO_V1_Measurement_Mapping_LOINC2HPO_Oct2020.xlsx/content"
)

COMPOSITION_SHEETS = {
    "OMOP2OBO_ChEBI_Mapping_Results": "CHEBI",
    "OMOP2OBO_UBERON_Mapping_Results": "UBERON",
    "OMOP2OBO_CL_Mapping_Results": "CL",
    "OMOP2OBO_PRO_Mapping_Results": "PR",
    "OMOP2OBO_NCBITa_Mapping_Results": "NCBITaxon",
}
HPO_SHEET = "OMOP2OBO_HPO_Mapping_Results"
CONCEPT_SHEET = "OMOP_CONCEPT_INFORMATION"

# Full whitespace set. DuckDB's trim() strips only spaces by default, but some OMOP2OBO
# URI cells carry a leading newline (e.g. '\nPR_P02768 | ...').
_WS = r"E' \t\r\n'"


# --------------------------------------------------------------------------------------
# Row filters
#
# Each entry is a (name, SQL predicate) pair over the `exploded` CTE's output columns.
# A row is written only if every predicate for its output holds. Adding a filter means
# appending a pair here and a case to tests/test_preprocess.py — nothing else changes.
# --------------------------------------------------------------------------------------

# Composition objects dropped regardless of which mapping sheet they came from.
EXCLUDED_OBJECTS = (
    # Homo sapiens is the specimen-source organism of essentially every clinical assay, so
    # a LOINC -> NCBITaxon:9606 edge asserts nothing that distinguishes one measurement
    # from another. The NCBITaxon sheet's informative content is the *non-human* organisms
    # (the infectious agents an assay detects), which are kept.
    "NCBITaxon:9606",
)


def _not_in(column: str, values: tuple[str, ...]) -> str:
    if not values:
        return "TRUE"
    return f"{column} NOT IN (" + ", ".join(f"'{v}'" for v in values) + ")"


COMPOSITION_FILTERS = (
    # OMOP2OBO marks concepts it could not map; those rows carry no object term.
    ("mapped", "lower(mapping_category) <> 'unmapped'"),
    # Guards against a term leaking in from the wrong ontology (or a mangled URI cell).
    ("object_matches_declared_ontology", "starts_with(object, object_ontology || ':')"),
    ("object_not_excluded", _not_in("object", EXCLUDED_OBJECTS)),
)

PHENOTYPE_FILTERS = (
    ("mapped", "lower(mapping_category) <> 'unmapped'"),
    ("object_is_hpo", "starts_with(object, 'HP:')"),
)


def _where(filters: tuple[tuple[str, str], ...]) -> str:
    return " AND ".join(f"({sql})" for _, sql in filters)


# --------------------------------------------------------------------------------------
# Queries
#
# Both builders take their input relations as arguments rather than hardcoding
# read_xlsx(...), so tests/test_preprocess.py can drive them with inline fixture rows
# instead of the real (downloaded) workbook.
# --------------------------------------------------------------------------------------


def _sheet(name: str) -> str:
    return f"read_xlsx('{XLSX}', sheet='{name}', all_varchar=true)"


def concept_query(concept_rel: str) -> str:
    """CONCEPT_ID -> LOINC CURIE, from the one sheet where CONCEPT_CODE is intact."""
    return f"""
        SELECT CONCEPT_ID AS concept_id, 'LOINC:' || trim(CONCEPT_CODE) AS subject
        FROM {concept_rel}
        WHERE upper(CONCEPT_VOCAB) LIKE '%LOINC%'
    """


def composition_query(edges_rel: str, concept_rel: str = "loinc_concept") -> str:
    """Composition edge rows from an OMOP2OBO-shaped mapping relation.

    `edges_rel` exposes object_ontology, CONCEPT_ID, ONTOLOGY_URI, ONTOLOGY_LOGIC,
    MAPPING_CATEGORY; `concept_rel` maps concept_id -> subject CURIE. One mapping row can
    list several terms ('CHEBI_1 | CHEBI_2'), so ONTOLOGY_URI is unnested to one edge
    each; regexp_replace (first match only) turns 'CHEBI_50904' -> 'CHEBI:50904'.
    """
    return f"""
        WITH exploded AS (
            SELECT c.subject AS subject,
                   regexp_replace(trim(u.uri, {_WS}), '_', ':') AS object,
                   e.object_ontology AS object_ontology,
                   trim(e.MAPPING_CATEGORY, {_WS}) AS mapping_category,
                   coalesce(trim(e.ONTOLOGY_LOGIC, {_WS}), '') AS mapping_logic
            FROM {edges_rel} e
            JOIN {concept_rel} c ON c.concept_id = e.CONCEPT_ID
            CROSS JOIN UNNEST(string_split(e.ONTOLOGY_URI, '|')) AS u(uri)
        )
        SELECT subject, object, object_ontology, mapping_category, mapping_logic
        FROM exploded
        WHERE {_where(COMPOSITION_FILTERS)}
    """


def phenotype_query(hpo_rel: str, concept_rel: str = "loinc_concept") -> str:
    """Phenotype edge rows, outcome-qualified.

    A "Normal"/"Negative" result means the phenotype is absent -> negated, which OMOP2OBO
    also encodes via NOT in ONTOLOGY_LOGIC. The result interpretation is preserved in the
    output for a later qualifier-modeling pass.
    """
    return f"""
        WITH exploded AS (
            SELECT c.subject AS subject,
                   regexp_replace(trim(u.uri, {_WS}), '_', ':') AS object,
                   coalesce(trim(h.RESULT_TYPE, {_WS}), '') AS result_type,
                   CASE WHEN upper(coalesce(h.ONTOLOGY_LOGIC, '')) LIKE '%NOT%'
                             OR lower(coalesce(trim(h.RESULT_TYPE, {_WS}), '')) IN ('normal', 'negative')
                        THEN 'true' ELSE 'false' END AS negated,
                   trim(h.MAPPING_CATEGORY, {_WS}) AS mapping_category
            FROM {hpo_rel} h
            JOIN {concept_rel} c ON c.concept_id = h.CONCEPT_ID
            CROSS JOIN UNNEST(string_split(h.ONTOLOGY_URI, '|')) AS u(uri)
        )
        SELECT subject, object, result_type, negated, mapping_category
        FROM exploded
        WHERE {_where(PHENOTYPE_FILTERS)}
    """


# --------------------------------------------------------------------------------------
# Hierarchy (CompLOINC OWL)
# --------------------------------------------------------------------------------------


def _loinc_curie(uri) -> str | None:
    """https://loinc.org/2345-7 -> LOINC:2345-7 ; LP/CC parts likewise. None otherwise."""
    m = re.match(r"https?://loinc\.org/(.+)$", str(uri))
    return f"LOINC:{m.group(1)}" if m else None


def _is_leaf_code(curie: str) -> bool:
    """LOINC:2345-7 is a leaf code; LOINC:LP14536-4 / LOINC:CC-123 are parts/groupers."""
    return bool(re.match(r"\d+-\d$", curie.split(":", 1)[1]))


def hierarchy_from_graph(g: rdflib.Graph) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(is_a edges, part nodes) from a CompLOINC graph.

    Only named LOINC->LOINC rdfs:subClassOf axioms are kept (anonymous restriction
    superclasses from the reasoner are skipped). Part nodes are the hierarchy participants
    that aren't plain leaf codes — the LP Part backbone plus CompLOINC CC groupers. Those
    aren't in the LOINC release table, so we emit them here (with their OWL labels) to keep
    the hierarchy connected.
    """
    labels = {}
    for s, _, o in g.triples((None, rdflib.RDFS.label, None)):
        c = _loinc_curie(s)
        if c:
            labels[c] = str(o)

    edges = set()
    participants = set()
    for s, _, o in g.triples((None, rdflib.RDFS.subClassOf, None)):
        cs, co = _loinc_curie(s), _loinc_curie(o)
        if cs and co:
            edges.add((cs, co))
            participants.update((cs, co))

    part_nodes = [(c, labels.get(c, "")) for c in sorted(participants) if not _is_leaf_code(c)]
    return sorted(edges), part_nodes


def _write_tsv(path: Path, header: list[str], rows) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(header)
        w.writerows(rows)


def extract_hierarchy() -> None:
    """data/comploinc.owl -> data/loinc_hierarchy_edges.tsv + data/loinc_part_nodes.tsv."""
    g = rdflib.Graph()
    g.parse(str(OWL))
    edges, part_nodes = hierarchy_from_graph(g)

    _write_tsv(DATA / "loinc_hierarchy_edges.tsv", ["subject", "object"], edges)
    _write_tsv(DATA / "loinc_part_nodes.tsv", ["id", "name"], part_nodes)

    print(f"hierarchy is_a edges: {len(edges)}")


# --------------------------------------------------------------------------------------


def _ensure_xlsx() -> None:
    if not Path(XLSX).exists():
        Path(DATA).mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(OMOP2OBO_URL, XLSX)


def _copy_to_tsv(con, query: str, path: Path) -> None:
    con.execute(f"COPY ({query}) TO '{path}' (FORMAT CSV, DELIMITER E'\t', HEADER)")


def main() -> None:
    _ensure_xlsx()
    con = duckdb.connect()
    con.execute("INSTALL excel; LOAD excel;")

    con.execute(f"CREATE TEMP TABLE loinc_concept AS {concept_query(_sheet(CONCEPT_SHEET))}")

    comp_union = " UNION ALL ".join(
        f"""SELECT '{prefix}' AS object_ontology, CONCEPT_ID,
                   ONTOLOGY_URI, ONTOLOGY_LOGIC, MAPPING_CATEGORY
            FROM {_sheet(sheet)}"""
        for sheet, prefix in COMPOSITION_SHEETS.items()
    )
    _copy_to_tsv(con, composition_query(f"({comp_union})"), DATA / "loinc_composition_edges.tsv")
    _copy_to_tsv(con, phenotype_query(_sheet(HPO_SHEET)), DATA / "loinc_phenotype_edges.tsv")

    def count(name: str) -> int:
        path = DATA / name
        return con.execute(f"SELECT count(*) FROM read_csv('{path}', delim='\t', header=true)").fetchone()[0]

    print(f"composition edges: {count('loinc_composition_edges.tsv')}")
    print(f"phenotype edges: {count('loinc_phenotype_edges.tsv')}")

    extract_hierarchy()


if __name__ == "__main__":
    main()
