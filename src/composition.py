import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import koza
from biolink_model.datamodel.pydanticmodel_v2 import Association

from _common import provenance

# PROVISIONAL predicate. These edges assert what characteristic a LOINC assay
# measures (its analyte -> ChEBI, specimen -> UBERON, cell -> CL, protein -> PR,
# organism -> NCBITaxon). The intended grounding is RO:0009006 "assay measures
# characteristic"; biolink has no exact predicate yet, so we emit related_to and
# resolve the predicate in a later modeling pass. The object category already
# distinguishes analyte vs specimen vs organism.
PREDICATE = "biolink:related_to"


@koza.transform_record()
def transform(koza, row: dict) -> list[Association]:
    knowledge_level, agent_type = provenance(row["mapping_category"])
    association = Association(
        subject=row["subject"],
        predicate=PREDICATE,
        object=row["object"],
        primary_knowledge_source="infores:omop2obo",
        aggregator_knowledge_source=["infores:monarchinitiative"],
        knowledge_level=knowledge_level,
        agent_type=agent_type,
    )
    return [association]
