"""Tests for the preprocess (filtering/flattening) stage.

These run before `just download`/`just prep` in the `just run` pipeline, so they must be
hermetic: no network, no reads of data/. The query builders take their input relations as
arguments precisely so the fixtures below can stand in for the real workbook.
"""

import duckdb
import pytest
import rdflib
from preprocess import (
    COMPOSITION_FILTERS,
    EXCLUDED_OBJECTS,
    PHENOTYPE_FILTERS,
    _is_leaf_code,
    _loinc_curie,
    _not_in,
    composition_query,
    hierarchy_from_graph,
    phenotype_query,
)

# (concept_id, concept_code, concept_vocab)
CONCEPTS = [("1", "2345-7", "LOINC"), ("2", "2731-8", "LOINC"), ("9", "XYZ", "SNOMED")]


@pytest.fixture
def con():
    """A connection with a `loinc_concept` table, mirroring what main() builds."""
    c = duckdb.connect()
    values = ", ".join(f"('{cid}', '{code}', '{vocab}')" for cid, code, vocab in CONCEPTS)
    c.execute(f"""
        CREATE TEMP TABLE loinc_concept AS
        SELECT concept_id, 'LOINC:' || trim(concept_code) AS subject
        FROM (VALUES {values}) AS t(concept_id, concept_code, concept_vocab)
        WHERE upper(concept_vocab) LIKE '%LOINC%'
    """)
    return c


def _composition(con, rows):
    """rows: (object_ontology, concept_id, ontology_uri, ontology_logic, mapping_category)."""
    values = ", ".join("(" + ", ".join(f"'{v}'" for v in r) + ")" for r in rows)
    rel = (
        f"(SELECT * FROM (VALUES {values}) AS t"
        "(object_ontology, CONCEPT_ID, ONTOLOGY_URI, ONTOLOGY_LOGIC, MAPPING_CATEGORY))"
    )
    return con.execute(composition_query(rel)).fetchall()


def _phenotype(con, rows):
    """rows: (concept_id, ontology_uri, ontology_logic, result_type, mapping_category)."""
    values = ", ".join("(" + ", ".join(f"'{v}'" for v in r) + ")" for r in rows)
    rel = (
        f"(SELECT * FROM (VALUES {values}) AS t"
        "(CONCEPT_ID, ONTOLOGY_URI, ONTOLOGY_LOGIC, RESULT_TYPE, MAPPING_CATEGORY))"
    )
    return con.execute(phenotype_query(rel)).fetchall()


# --- composition ----------------------------------------------------------------------


def test_composition_maps_subject_and_object(con):
    (row,) = _composition(con, [("CHEBI", "1", "CHEBI_17234", "", "Manual One-to-One Concept")])
    subject, obj, ontology, category, logic = row
    assert (subject, obj, ontology) == ("LOINC:2345-7", "CHEBI:17234", "CHEBI")
    assert category == "Manual One-to-One Concept"


def test_composition_unnests_multiple_uris(con):
    rows = _composition(con, [("CHEBI", "1", "CHEBI_1 | CHEBI_2 | CHEBI_3", "", "Manual")])
    assert sorted(r[1] for r in rows) == ["CHEBI:1", "CHEBI:2", "CHEBI:3"]


def test_composition_trims_leading_newline_in_uri_cell(con):
    """Some OMOP2OBO URI cells start with a newline; a space-only trim would mangle them."""
    (row,) = _composition(con, [("PR", "1", "\nPR_P02768", "", "Manual")])
    assert row[1] == "PR:P02768"


def test_composition_drops_unmapped(con):
    assert _composition(con, [("CHEBI", "1", "CHEBI_17234", "", "Unmapped")]) == []


def test_composition_drops_object_from_wrong_ontology(con):
    """A CL term listed on the UBERON sheet must not become an UBERON edge."""
    assert _composition(con, [("UBERON", "1", "CL_0000738", "", "Manual")]) == []


def test_composition_drops_excluded_human_taxon(con):
    """NCBITaxon:9606 is the specimen source of nearly every assay -> no signal."""
    assert _composition(con, [("NCBITaxon", "1", "NCBITaxon_9606", "", "Manual")]) == []


def test_composition_keeps_non_human_taxon(con):
    """The exclusion is exact-match: infectious agents an assay detects are kept."""
    (row,) = _composition(con, [("NCBITaxon", "1", "NCBITaxon_96061", "", "Manual")])
    assert row[1] == "NCBITaxon:96061"
    (row,) = _composition(con, [("NCBITaxon", "1", "NCBITaxon_1280", "", "Manual")])
    assert row[1] == "NCBITaxon:1280"


def test_composition_excludes_human_from_a_multi_uri_cell(con):
    """Exclusion happens after the unnest, so siblings in the same cell survive."""
    rows = _composition(con, [("NCBITaxon", "1", "NCBITaxon_9606 | NCBITaxon_1280", "", "Manual")])
    assert [r[1] for r in rows] == ["NCBITaxon:1280"]


def test_composition_drops_row_with_unresolvable_concept_id(con):
    """CONCEPT_ID 9 is SNOMED, so it never enters loinc_concept; 404 is absent entirely."""
    assert _composition(con, [("CHEBI", "9", "CHEBI_1", "", "Manual")]) == []
    assert _composition(con, [("CHEBI", "404", "CHEBI_1", "", "Manual")]) == []


# --- phenotype ------------------------------------------------------------------------


def test_phenotype_maps_row(con):
    (row,) = _phenotype(con, [("1", "HP_0003074", "", "High", "Manual One-to-One Concept")])
    subject, obj, result_type, negated, category = row
    assert (subject, obj, result_type, negated) == ("LOINC:2345-7", "HP:0003074", "High", "false")


@pytest.mark.parametrize(
    ("logic", "result_type", "expected"),
    [
        ("", "High", "false"),
        ("", "Low", "false"),
        ("", "Positive", "false"),
        ("", "Normal", "true"),
        ("", "Negative", "true"),
        ("", "normal", "true"),
        ("NOT HP_0003074", "High", "true"),
    ],
)
def test_phenotype_negation(con, logic, result_type, expected):
    (row,) = _phenotype(con, [("1", "HP_0003074", logic, result_type, "Manual")])
    assert row[3] == expected


def test_phenotype_drops_unmapped(con):
    assert _phenotype(con, [("1", "HP_0003074", "", "High", "Unmapped")]) == []


def test_phenotype_drops_non_hpo_object(con):
    assert _phenotype(con, [("1", "CHEBI_17234", "", "High", "Manual")]) == []


# --- filter registry ------------------------------------------------------------------


def test_filter_names_are_unique():
    for filters in (COMPOSITION_FILTERS, PHENOTYPE_FILTERS):
        names = [name for name, _ in filters]
        assert len(names) == len(set(names))


def test_not_in_is_a_noop_when_nothing_is_excluded():
    """An emptied EXCLUDED_OBJECTS must not produce invalid SQL."""
    assert _not_in("object", ()) == "TRUE"
    assert _not_in("object", ("A:1", "B:2")) == "object NOT IN ('A:1', 'B:2')"


def test_human_taxon_is_excluded():
    assert "NCBITaxon:9606" in EXCLUDED_OBJECTS


# --- hierarchy ------------------------------------------------------------------------


def test_loinc_curie():
    assert _loinc_curie("https://loinc.org/2345-7") == "LOINC:2345-7"
    assert _loinc_curie("http://loinc.org/LP14536-4") == "LOINC:LP14536-4"
    assert _loinc_curie("http://purl.obolibrary.org/obo/CHEBI_17234") is None


def test_is_leaf_code():
    assert _is_leaf_code("LOINC:2345-7")
    assert not _is_leaf_code("LOINC:LP14536-4")
    assert not _is_leaf_code("LOINC:CC-123")


def _graph(triples):
    g = rdflib.Graph()
    for s, p, o in triples:
        g.add((s, p, o))
    return g


def test_hierarchy_keeps_named_loinc_edges_and_splits_part_nodes():
    leaf, part = rdflib.URIRef("https://loinc.org/2345-7"), rdflib.URIRef("https://loinc.org/LP14536-4")
    g = _graph([
        (leaf, rdflib.RDFS.subClassOf, part),
        (part, rdflib.RDFS.label, rdflib.Literal("Glucose")),
        (leaf, rdflib.RDFS.label, rdflib.Literal("Glucose [Mass/volume]")),
    ])
    edges, part_nodes = hierarchy_from_graph(g)
    assert edges == [("LOINC:2345-7", "LOINC:LP14536-4")]
    # Leaf codes come from the LOINC release table, so only the part is emitted here.
    assert part_nodes == [("LOINC:LP14536-4", "Glucose")]


def test_hierarchy_skips_anonymous_and_foreign_superclasses():
    leaf = rdflib.URIRef("https://loinc.org/2345-7")
    g = _graph([
        (leaf, rdflib.RDFS.subClassOf, rdflib.BNode()),
        (leaf, rdflib.RDFS.subClassOf, rdflib.URIRef("http://purl.obolibrary.org/obo/CHEBI_17234")),
    ])
    assert hierarchy_from_graph(g) == ([], [])


def test_hierarchy_part_node_without_label_gets_empty_name():
    leaf, part = rdflib.URIRef("https://loinc.org/2345-7"), rdflib.URIRef("https://loinc.org/LP1-1")
    edges, part_nodes = hierarchy_from_graph(_graph([(leaf, rdflib.RDFS.subClassOf, part)]))
    assert part_nodes == [("LOINC:LP1-1", "")]


def test_hierarchy_deduplicates_edges():
    leaf, part = rdflib.URIRef("https://loinc.org/2345-7"), rdflib.URIRef("https://loinc.org/LP1-1")
    g = _graph([(leaf, rdflib.RDFS.subClassOf, part)])
    g.add((leaf, rdflib.RDFS.subClassOf, part))
    edges, _ = hierarchy_from_graph(g)
    assert len(edges) == 1
