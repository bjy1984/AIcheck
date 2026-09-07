"""P0 2.2 开关：默认关时包一字不改；stage1 加类型拆节点；stage2 才改必传。"""

from __future__ import annotations

import pytest

from libs.business_pack.loader import (
    DEFAULT_BUSINESS_PACK_ID,
    build_project_requirements,
    load_business_pack,
    validate_business_pack,
)
from libs.business_pack.welding_material_types_v2 import (
    FLAG_ENV,
    apply_welding_material_types_v2,
    stage,
)


def _reqs(pack, node_id):
    return {item["materialTypeCode"]: item for item in build_project_requirements(pack) if item["nodeId"] == node_id}


def test_flag_off_leaves_pack_untouched(monkeypatch) -> None:
    monkeypatch.delenv(FLAG_ENV, raising=False)
    load_business_pack.cache_clear()
    pack = load_business_pack(DEFAULT_BUSINESS_PACK_ID)
    codes = {item["code"] for item in pack["materialTypes"]}
    assert stage() == "off" and "weldingMaterialTypesV2" not in pack
    assert "wps" not in codes and "pmi_report" not in codes and "wps_pqr" in codes
    assert _reqs(pack, 26)["welding_material_certificate"]["requiredType"] == "条件必传"
    assert apply_welding_material_types_v2(pack) is pack


def test_stage1_adds_types_and_splits_node_25_without_forcing_required(monkeypatch) -> None:
    monkeypatch.setenv(FLAG_ENV, "stage1")
    load_business_pack.cache_clear()
    try:
        pack = load_business_pack(DEFAULT_BUSINESS_PACK_ID)
        assert pack["weldingMaterialTypesV2"] == "stage1" and validate_business_pack(pack)["ok"]
        codes = {item["code"] for item in pack["materialTypes"]}
        assert {"wps", "pqr", "welding_process_card", "platform_verification", "pmi_report", "wps_pqr"} <= codes, "旧 wps_pqr 保留给已绑定资料"
        node25 = _reqs(pack, 25)
        assert "wps_pqr" not in node25 and {"wps", "pqr", "welding_process_card", "pipeline_summary"} <= set(node25)
        assert _reqs(pack, 29)["wps"]["requiredType"] == "条件必传" and "wps_pqr" not in _reqs(pack, 29)
        node24 = _reqs(pack, 24)
        assert node24["platform_verification"]["responsibleParty"] == "系统自动产生"
        assert node24["external_query_screenshot"]["requiredType"] == "可选"
        assert _reqs(pack, 16)["pmi_report"]["requiredType"] == "条件必传" and "pmi_report" in _reqs(pack, 21)
        # stage1 先跑一周：证明与施焊记录仍是条件必传
        assert _reqs(pack, 26)["welding_material_certificate"]["requiredType"] == "条件必传"
        assert _reqs(pack, 29)["welding_record"]["requiredType"] == "条件必传"
        management = next(item for item in pack["materialTypes"] if item["code"] == "welding_material_management_record")
        assert management["subKinds"] == ["acceptance", "drying", "issue", "return"]
        ids = [item["id"] for item in build_project_requirements(pack)]
        assert len(ids) == len(set(ids)), "新增要求的 id 不能撞旧编号"
    finally:
        load_business_pack.cache_clear()


def test_stage2_makes_certificate_and_welding_record_required(monkeypatch) -> None:
    monkeypatch.setenv(FLAG_ENV, "stage2")
    load_business_pack.cache_clear()
    try:
        pack = load_business_pack(DEFAULT_BUSINESS_PACK_ID)
        assert _reqs(pack, 26)["welding_material_certificate"]["requiredType"] == "必传"
        assert _reqs(pack, 29)["welding_record"]["requiredType"] == "必传"
        off = apply_welding_material_types_v2(pack, stage_name="off")
        assert off is pack
    finally:
        load_business_pack.cache_clear()


@pytest.mark.parametrize("value", ["", "on", "STAGE3", "yes"])
def test_unknown_flag_values_mean_off(monkeypatch, value) -> None:
    monkeypatch.setenv(FLAG_ENV, value)
    assert stage() == "off"
