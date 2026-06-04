import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import koza
from biolink_model.datamodel.pydanticmodel_v2 import ClinicalMeasurement


@koza.transform_record()
def transform(koza, row: dict) -> list[ClinicalMeasurement]:
    """One LOINC release row -> one biolink:ClinicalMeasurement node.

    Source is the full LOINC table repackaged by the Tuva Project (~104k codes,
    public S3). Deprecated codes are kept but flagged (`deprecated=True`) rather than
    dropped, so OMOP2OBO edges referencing codes deprecated since its 2018 LOINC still
    land on a node.
    """
    loinc_id = "LOINC:" + row["loinc"].strip()
    name = (row.get("long_common_name") or row.get("short_name") or "").strip() or None
    deprecated = (row.get("status") or "").strip().upper() == "DEPRECATED"

    # ClinicalMeasurement is a biolink `attribute`, so `has_attribute_type` is required;
    # for a LOINC concept node the describing class is the LOINC code itself. (Flagged for
    # the modeling pass — see README.)
    node = ClinicalMeasurement(
        id=loinc_id,
        name=name,
        has_attribute_type=loinc_id,
        deprecated=True if deprecated else None,
        provided_by=["infores:loinc"],
    )
    return [node]
