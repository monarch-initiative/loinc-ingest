"""Flatten the upstream sources into tidy KGX-ready TSVs for the koza transforms.

  data/omop2obo_meas.xlsx  ->  data/loinc_composition_edges.tsv   (ChEBI/UBERON/CL/PR/NCBITaxon)   [DuckDB]
                               data/loinc_phenotype_edges.tsv      (HPO, outcome-qualified)         [DuckDB]
  data/comploinc.owl       ->  data/loinc_hierarchy_edges.tsv      (is_a)                            [rdflib]
                               data/loinc_part_nodes.tsv           (LP Part / CC grouper nodes)      [rdflib]

Leaf-code nodes come from the LOINC release table (`data/loinc.csv.gz`) read directly by
the `nodes` koza transform.

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


def _ensure_xlsx() -> None:
    if not Path(XLSX).exists():
        Path(DATA).mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(OMOP2OBO_URL, XLSX)


def _loinc_curie(uri) -> str | None:
    """https://loinc.org/2345-7 -> LOINC:2345-7 ; LP/CC parts likewise. None otherwise."""
    m = re.match(r"https?://loinc\.org/(.+)$", str(uri))
    return f"LOINC:{m.group(1)}" if m else None


def extract_hierarchy() -> None:
    """Extract the is_a hierarchy + LP/CC part nodes from the CompLOINC OWL.

      data/comploinc.owl -> data/loinc_hierarchy_edges.tsv  (subject is_a object)
                            data/loinc_part_nodes.tsv        (LP/CC parent nodes + labels)

    Only named LOINC->LOINC rdfs:subClassOf axioms are kept (anonymous restriction
    superclasses from the reasoner are skipped). Parent LP Parts / CC groupers aren't in
    the LOINC release table, so we emit them as nodes here (with their OWL labels) to keep
    the hierarchy connected.
    """
    g = rdflib.Graph()
    g.parse(str(OWL))

    labels = {}
    for s, _, o in g.triples((None, rdflib.RDFS.label, None)):
        c = _loinc_curie(s)
        if c:
            labels[c] = str(o)

    edges = []
    participants = set()
    for s, _, o in g.triples((None, rdflib.RDFS.subClassOf, None)):
        cs, co = _loinc_curie(s), _loinc_curie(o)
        if cs and co:
            edges.append((cs, co))
            participants.update((cs, co))

    with (DATA / "loinc_hierarchy_edges.tsv").open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["subject", "object"])
        w.writerows(sorted(set(edges)))

    # Part nodes = hierarchy participants that aren't plain leaf codes (those come from
    # the LOINC table). i.e. the LP Part backbone + CompLOINC CC groupers.
    with (DATA / "loinc_part_nodes.tsv").open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["id", "name"])
        for c in sorted(participants):
            local = c.split(":", 1)[1]
            if not re.match(r"\d+-\d$", local):  # keep LP*/CC* (skip numeric leaf codes)
                w.writerow([c, labels.get(c, "")])

    print(f"hierarchy is_a edges: {len(set(edges))}")

COMPOSITION_SHEETS = {
    "OMOP2OBO_ChEBI_Mapping_Results": "CHEBI",
    "OMOP2OBO_UBERON_Mapping_Results": "UBERON",
    "OMOP2OBO_CL_Mapping_Results": "CL",
    "OMOP2OBO_PRO_Mapping_Results": "PR",
    "OMOP2OBO_NCBITa_Mapping_Results": "NCBITaxon",
}
HPO_SHEET = "OMOP2OBO_HPO_Mapping_Results"


def _sheet(name: str) -> str:
    return f"read_xlsx('{XLSX}', sheet='{name}', all_varchar=true)"


def main() -> None:
    _ensure_xlsx()
    con = duckdb.connect()
    con.execute("INSTALL excel; LOAD excel;")

    # CONCEPT_ID -> LOINC CURIE, from the one sheet where CONCEPT_CODE is intact.
    con.execute(f"""
        CREATE TEMP TABLE loinc_concept AS
        SELECT CONCEPT_ID AS concept_id, 'LOINC:' || trim(CONCEPT_CODE) AS subject
        FROM {_sheet('OMOP_CONCEPT_INFORMATION')}
        WHERE upper(CONCEPT_VOCAB) LIKE '%LOINC%'
    """)

    # One mapping row can list several terms ('CHEBI_1 | CHEBI_2'); unnest to one edge each.
    # regexp_replace (first match only) turns 'CHEBI_50904' -> 'CHEBI:50904'.
    comp_union = " UNION ALL ".join(
        f"""SELECT '{prefix}' AS object_ontology, CONCEPT_ID,
                   ONTOLOGY_URI, ONTOLOGY_LOGIC, MAPPING_CATEGORY
            FROM {_sheet(sheet)}"""
        for sheet, prefix in COMPOSITION_SHEETS.items()
    )
    # WS = full whitespace set: DuckDB trim() strips only spaces by default, but some
    # OMOP2OBO URI cells carry a leading newline (e.g. '\nPR_P02768 | ...').
    ws = r"E' \t\r\n'"
    con.execute(f"""
        COPY (
            WITH edges AS ({comp_union}),
            exploded AS (
                SELECT c.subject AS subject,
                       regexp_replace(trim(u.uri, {ws}), '_', ':') AS object,
                       e.object_ontology AS object_ontology,
                       trim(e.MAPPING_CATEGORY, {ws}) AS mapping_category,
                       coalesce(trim(e.ONTOLOGY_LOGIC, {ws}), '') AS mapping_logic
                FROM edges e
                JOIN loinc_concept c ON c.concept_id = e.CONCEPT_ID
                CROSS JOIN UNNEST(string_split(e.ONTOLOGY_URI, '|')) AS u(uri)
                WHERE lower(trim(e.MAPPING_CATEGORY, {ws})) <> 'unmapped'
            )
            SELECT subject, object, object_ontology, mapping_category, mapping_logic
            FROM exploded
            WHERE starts_with(object, object_ontology || ':')
        ) TO '{DATA / "loinc_composition_edges.tsv"}' (FORMAT CSV, DELIMITER E'\t', HEADER)
    """)

    # Phenotype: outcome-qualified. "Normal"/"Negative" result -> phenotype absent (negated),
    # which OMOP2OBO also encodes via NOT in ONTOLOGY_LOGIC.
    con.execute(f"""
        COPY (
            WITH exploded AS (
                SELECT c.subject AS subject,
                       regexp_replace(trim(u.uri, {ws}), '_', ':') AS object,
                       coalesce(trim(h.RESULT_TYPE, {ws}), '') AS result_type,
                       CASE WHEN upper(coalesce(h.ONTOLOGY_LOGIC, '')) LIKE '%NOT%'
                                 OR lower(coalesce(trim(h.RESULT_TYPE, {ws}), '')) IN ('normal', 'negative')
                            THEN 'true' ELSE 'false' END AS negated,
                       trim(h.MAPPING_CATEGORY, {ws}) AS mapping_category
                FROM {_sheet(HPO_SHEET)} h
                JOIN loinc_concept c ON c.concept_id = h.CONCEPT_ID
                CROSS JOIN UNNEST(string_split(h.ONTOLOGY_URI, '|')) AS u(uri)
                WHERE lower(trim(h.MAPPING_CATEGORY, {ws})) <> 'unmapped'
            )
            SELECT subject, object, result_type, negated, mapping_category
            FROM exploded
            WHERE starts_with(object, 'HP:')
        ) TO '{DATA / "loinc_phenotype_edges.tsv"}' (FORMAT CSV, DELIMITER E'\t', HEADER)
    """)

    def count(name: str) -> int:
        path = DATA / name
        return con.execute(f"SELECT count(*) FROM read_csv('{path}', delim='\t', header=true)").fetchone()[0]

    print(f"composition edges: {count('loinc_composition_edges.tsv')}")
    print(f"phenotype edges: {count('loinc_phenotype_edges.tsv')}")

    extract_hierarchy()


if __name__ == "__main__":
    main()
