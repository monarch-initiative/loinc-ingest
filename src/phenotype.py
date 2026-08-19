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
# (RO:0002610) is the least-wrong canonical fit.
PREDICATE = "biolink:correlated_with"

# Normal/Negative results are dropped rather than emitted with negated=True.
# Upstream, the NOT scopes over "the patient's state, given this result"; biolink's
# negated scopes over subject-predicate-object. Without a qualifier to carry the
# result level, emitting them asserts that the test is unrelated to the phenotype --
# contradicting the High/Low/Positive edges the same LOINC code also carries, and in
# many cases negating a direct parent of a term asserted positively.
#
# Little is lost: of the suppressed edges, 65% restate a term the same code asserts
# positively and 34% point at an ancestor reachable by subclass closure from a
# positive edge. Restore them once a result qualifier exists -- result_type is still
# carried in data/loinc_phenotype_edges.tsv. See the migration proposal:
# https://gist.github.com/kevinschaper/1f16ae05f15001c28cfa675631923864


@koza.transform_record()
def transform(koza, row: dict) -> list[Association]:
    if row["negated"].strip().lower() == "true":
        return []

    knowledge_level, agent_type = provenance(row["mapping_category"])
    association = Association(
        id="uuid:" + str(uuid.uuid1()),
        subject=row["subject"],
        predicate=PREDICATE,
        object=row["object"],
        negated=False,
        primary_knowledge_source="infores:loinc2hpo",
        aggregator_knowledge_source=["infores:omop2obo"],
        knowledge_level=knowledge_level,
        agent_type=agent_type,
    )
    return [association]
