from __future__ import annotations

import re
from typing import Any

PROFILE_VERSION = "material-product-standard-profiles-v1"

# This registry deliberately freezes only document/test-item requirements that have
# been verified for the pilot. Grade-specific numeric limits must be supplied as
# structured acceptanceLimits facts; tools are not allowed to guess them.
MATERIAL_PRODUCT_STANDARD_PROFILES: dict[str, dict[str, Any]] = {
    "GB/T 12459-2025": {
        "aliases": ("GB/T12459-2025", "GBT12459-2025", "GB/T 12459—2025"),
        "productFamily": "steel_butt_welding_fitting",
        "requiredCertificateFields": ("standardRef", "productName", "specification", "materialGrade", "batchNo", "conclusion"),
        "coreTestItems": ("chemical_composition", "mechanical_properties"),
        "sourceClauses": ("第10章", "第11章"),
    },
    "GB/T 13401-2025": {
        "aliases": ("GB/T13401-2025", "GBT13401-2025", "GB/T 13401—2025"),
        "productFamily": "steel_plate_butt_welding_fitting",
        "requiredCertificateFields": ("standardRef", "productName", "specification", "materialGrade", "batchNo", "conclusion"),
        "coreTestItems": ("chemical_composition", "mechanical_properties", "inspection_and_test"),
        "sourceClauses": ("第8章", "第10章", "第11章"),
    },
    "GB/T 8163-2018": {
        "aliases": ("GB/T8163-2018", "GBT8163-2018", "GB/T 8163—2018"),
        "productFamily": "seamless_steel_pipe_for_fluid_service",
        "requiredCertificateFields": ("standardRef", "productName", "specification", "materialGrade", "batchNo", "deliveryCondition", "conclusion"),
        "coreTestItems": ("chemical_composition", "tensile_test", "hydrostatic_or_ndt"),
        "sourceClauses": ("检验规则", "包装、标志和质量证明书"),
    },
    "GB/T 3087-2022": {
        "aliases": ("GB/T3087-2022", "GBT3087-2022", "GB/T 3087—2022"),
        "productFamily": "seamless_steel_pipe_for_low_medium_pressure_boiler",
        "requiredCertificateFields": ("standardRef", "productName", "specification", "materialGrade", "batchNo", "deliveryCondition", "conclusion"),
        "coreTestItems": ("chemical_composition", "tensile_test", "flattening_or_flaring", "hydrostatic_or_ndt"),
        "sourceClauses": ("检验和试验", "质量证明书"),
    },
    "GB/T 5310-2023": {
        "aliases": ("GB/T5310-2023", "GBT5310-2023", "GB/T 5310—2023"),
        "productFamily": "seamless_steel_pipe_for_high_pressure_boiler",
        "requiredCertificateFields": ("standardRef", "productName", "specification", "materialGrade", "batchNo", "deliveryCondition", "conclusion"),
        "coreTestItems": ("chemical_composition", "tensile_test", "impact_test", "hydrostatic_or_ndt"),
        "sourceClauses": ("检验和试验", "质量证明书"),
    },
    "GB/T 9948-2025": {
        "aliases": ("GB/T9948-2025", "GBT9948-2025", "GB/T 9948—2025"),
        "productFamily": "seamless_steel_pipe_for_petrochemical_service",
        "requiredCertificateFields": ("standardRef", "productName", "specification", "materialGrade", "batchNo", "deliveryCondition", "conclusion"),
        "coreTestItems": ("chemical_composition", "tensile_test", "hydrostatic_or_ndt"),
        "sourceClauses": ("检验和试验", "质量证明书"),
    },
    "GB/T 14976-2025": {
        "aliases": ("GB/T14976-2025", "GBT14976-2025", "GB/T 14976—2025"),
        "productFamily": "stainless_seamless_steel_pipe_for_fluid_service",
        "requiredCertificateFields": ("standardRef", "productName", "specification", "materialGrade", "batchNo", "deliveryCondition", "conclusion"),
        "coreTestItems": ("chemical_composition", "tensile_test", "hydrostatic_or_ndt"),
        "sourceClauses": ("7.3", "7.7", "第9章", "第10章", "第11章"),
    },
    "GB/T 12771-2019": {
        "aliases": ("GB/T12771-2019", "GBT12771-2019", "GB/T 12771—2019"),
        "productFamily": "stainless_welded_steel_pipe_for_fluid_service",
        "requiredCertificateFields": ("standardRef", "productName", "specification", "materialGrade", "batchNo", "deliveryCondition", "conclusion"),
        "coreTestItems": ("chemical_composition", "tensile_test", "weld_ndt", "hydrostatic_or_ndt"),
        "sourceClauses": ("无损检测", "检验规则", "标志和质量证明书"),
    },
}


def canonical_standard_ref(value: Any) -> str | None:
    normalized = _standard_key(value)
    if not normalized:
        return None
    for standard_ref, profile in MATERIAL_PRODUCT_STANDARD_PROFILES.items():
        candidates = (standard_ref, *profile.get("aliases", ()))
        if normalized in {_standard_key(item) for item in candidates}:
            return standard_ref
    return None


def resolve_material_standard_profile(value: Any) -> dict[str, Any] | None:
    canonical = canonical_standard_ref(value)
    if not canonical:
        return None
    return {"standardRef": canonical, "profileVersion": PROFILE_VERSION, **MATERIAL_PRODUCT_STANDARD_PROFILES[canonical]}


def _standard_key(value: Any) -> str:
    text = str(value or "").upper().replace("—", "-").replace("–", "-")
    return re.sub(r"[^A-Z0-9]", "", text)
