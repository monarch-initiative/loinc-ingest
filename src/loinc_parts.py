import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import koza
from biolink_model.datamodel.pydanticmodel_v2 import ClinicalMeasurement


@koza.transform_record()
def transform(koza, row: dict) -> list[ClinicalMeasurement]:
    """A LOINC Part (LP…) or CompLOINC grouper (CC…) — the is_a backbone above leaf codes.

    These aren't in the LOINC release table (which has only leaf codes), so we emit them
    here from CompLOINC with their OWL labels. Category is ClinicalMeasurement for now (a
    grouping over measurements); revisit in the modeling pass — see README.
    """
    node = ClinicalMeasurement(
        id=row["id"],
        name=row["name"] or None,
        has_attribute_type=row["id"],
        provided_by=["infores:comploinc"],
    )
    return [node]
