import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import koza
from biolink_model.datamodel.pydanticmodel_v2 import Association

from _common import provenance

# PROVISIONAL predicate. An abnormal result of a LOINC test indicates an HPO
# phenotype (e.g. high glucose -> hyperglycemia). biolink has no purpose-built
# predicate for "abnormal-measurement-result indicates phenotype"; correlated_with
# (RO:0002610) is the least-wrong canonical fit. A "Normal"/"Negative" result means
# the phenotype is absent, carried here as negated=True. The result interpretation
# (High/Low/Normal/Positive/Negative) is preserved in the prep TSV for a later
# qualifier-modeling pass.
PREDICATE = "biolink:correlated_with"


@koza.transform_record()
def transform(koza, row: dict) -> list[Association]:
    knowledge_level, agent_type = provenance(row["mapping_category"])
    association = Association(
        id="uuid:" + str(uuid.uuid1()),
        subject=row["subject"],
        predicate=PREDICATE,
        object=row["object"],
        negated=row["negated"].strip().lower() == "true",
        primary_knowledge_source="infores:loinc2hpo",
        aggregator_knowledge_source=["infores:omop2obo"],
        knowledge_level=knowledge_level,
        agent_type=agent_type,
    )
    return [association]
