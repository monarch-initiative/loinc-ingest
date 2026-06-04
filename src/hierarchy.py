import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import koza
from biolink_model.datamodel.pydanticmodel_v2 import AgentTypeEnum, Association, KnowledgeLevelEnum

# is_a from CompLOINC's rdfs:subClassOf. subclass_of IS the biolink is_a predicate
# (unlike the other edge types, this one is not provisional).
PREDICATE = "biolink:subclass_of"


@koza.transform_record()
def transform(koza, row: dict) -> list[Association]:
    association = Association(
        id="uuid:" + str(uuid.uuid1()),
        subject=row["subject"],
        predicate=PREDICATE,
        object=row["object"],
        primary_knowledge_source="infores:comploinc",
        aggregator_knowledge_source=["infores:monarchinitiative"],
        knowledge_level=KnowledgeLevelEnum.knowledge_assertion,
        agent_type=AgentTypeEnum.automated_agent,  # CompLOINC computes the hierarchy
    )
    return [association]
