"""Shared helpers for the loinc-ingest transforms."""

from biolink_model.datamodel.pydanticmodel_v2 import AgentTypeEnum, KnowledgeLevelEnum

# OMOP2OBO records how each mapping was produced. Manual curation is a knowledge
# assertion by a human; the automatic/similarity tiers are machine predictions.
_MANUAL = "manual"


def provenance(mapping_category: str) -> tuple[KnowledgeLevelEnum, AgentTypeEnum]:
    if _MANUAL in (mapping_category or "").lower():
        return KnowledgeLevelEnum.knowledge_assertion, AgentTypeEnum.manual_agent
    return KnowledgeLevelEnum.prediction, AgentTypeEnum.automated_agent
