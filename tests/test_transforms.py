"""Smoke tests for the loinc-ingest transforms (koza 2.x: call the transform directly)."""

from composition import transform as composition_transform
from hierarchy import transform as hierarchy_transform
from loinc_parts import transform as parts_transform
from nodes import transform as node_transform
from phenotype import transform as phenotype_transform


def _loinc_row(**over):
    row = {"loinc": "2345-7", "long_common_name": "Glucose [Mass/volume] in Serum or Plasma",
           "short_name": "Glucose SerPl-mCnc", "status": "ACTIVE"}
    row.update(over)
    return row


def test_node_is_clinical_measurement():
    (node,) = node_transform(None, _loinc_row())
    assert node.id == "LOINC:2345-7"
    assert "biolink:ClinicalMeasurement" in node.category
    assert node.name == "Glucose [Mass/volume] in Serum or Plasma"
    assert node.has_attribute_type == "LOINC:2345-7"


def test_deprecated_node_flagged_not_dropped():
    (node,) = node_transform(None, _loinc_row(status="DEPRECATED"))
    assert node.deprecated is True


def test_active_node_not_flagged_deprecated():
    (node,) = node_transform(None, _loinc_row())
    assert node.deprecated is None


def test_node_falls_back_to_shortname():
    (node,) = node_transform(None, _loinc_row(long_common_name=""))
    assert node.name == "Glucose SerPl-mCnc"


def test_composition_edge_to_chebi():
    (edge,) = composition_transform(None, {
        "subject": "LOINC:2345-7", "object": "CHEBI:17234", "object_ontology": "CHEBI",
        "mapping_category": "Manual One-to-One Concept", "mapping_logic": "",
    })
    assert edge.subject == "LOINC:2345-7"
    assert edge.object == "CHEBI:17234"
    assert edge.primary_knowledge_source == "infores:omop2obo"


def test_composition_provenance_from_mapping_category():
    (manual,) = composition_transform(None, {
        "subject": "LOINC:1", "object": "CHEBI:1", "object_ontology": "CHEBI",
        "mapping_category": "Manual One-to-One Concept", "mapping_logic": "",
    })
    (auto,) = composition_transform(None, {
        "subject": "LOINC:2", "object": "CHEBI:2", "object_ontology": "CHEBI",
        "mapping_category": "Automatic One-to-One Ancestor", "mapping_logic": "",
    })
    assert manual.knowledge_level == "knowledge_assertion" and manual.agent_type == "manual_agent"
    assert auto.knowledge_level == "prediction" and auto.agent_type == "automated_agent"


def test_part_node():
    (node,) = parts_transform(None, {"id": "LOINC:LP14536-4", "name": "Glucose"})
    assert node.id == "LOINC:LP14536-4"
    assert "biolink:ClinicalMeasurement" in node.category
    assert node.provided_by == ["infores:comploinc"]


def test_hierarchy_is_a_edge():
    (edge,) = hierarchy_transform(None, {"subject": "LOINC:2345-7", "object": "LOINC:LP14536-4"})
    assert edge.subject == "LOINC:2345-7"
    assert edge.object == "LOINC:LP14536-4"
    assert edge.predicate == "biolink:subclass_of"
    assert edge.primary_knowledge_source == "infores:comploinc"


def _phenotype_row(**over):
    row = {"subject": "LOINC:2345-7", "object": "HP:0003074", "result_type": "High",
           "negated": "false", "mapping_category": "Manual One-to-One Concept"}
    row.update(over)
    return row


def test_phenotype_abnormal_result_emits_edge():
    (edge,) = phenotype_transform(None, _phenotype_row())
    assert edge.object == "HP:0003074"
    assert edge.negated is False


def test_phenotype_result_level_selects_directional_predicate():
    """High/Low pick directional children of correlated_with. For the 404 pairs where both
    result levels map to the same HP term, the predicate is the only thing keeping them apart."""
    (high,) = phenotype_transform(None, _phenotype_row(object="HP:0032146", result_type="High"))
    (low,) = phenotype_transform(None, _phenotype_row(object="HP:0032146", result_type="Low"))
    assert high.predicate == "biolink:positively_correlated_with"
    assert low.predicate == "biolink:negatively_correlated_with"


def test_phenotype_presence_assay_keeps_undirected_predicate():
    (edge,) = phenotype_transform(None, _phenotype_row(result_type="Positive"))
    assert edge.predicate == "biolink:correlated_with"


def test_phenotype_unknown_result_falls_back_to_parent_predicate():
    (edge,) = phenotype_transform(None, _phenotype_row(result_type="Indeterminate"))
    assert edge.predicate == "biolink:correlated_with"


def test_phenotype_normal_result_suppressed():
    """Normal/Negative rows carry negated=true upstream, where the NOT scopes over the
    result rather than the subject-predicate-object triple. Emitting them contradicts the
    High/Low edges the same LOINC code asserts, so they are dropped until a result
    qualifier can carry the scope."""
    assert phenotype_transform(None, _phenotype_row(
        object="HP:0011015", result_type="Normal", negated="true")) == []
