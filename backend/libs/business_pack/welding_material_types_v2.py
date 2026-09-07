"""P0 2.2 资料类型变更，放在开关后面（优化计划 §2.2、§18.7）。

为什么不直接改 materials.yaml / nodes.yaml：生产 admin_config 里的材料审查点按 materialTypeCode
挂载，而 164 条审查点的 id 与资产错位（2.4 迁移未批）。先改包会让新类型（wps / pqr /
welding_process_card / platform_verification / pmi_report）在生产上没有任何审查点可挂，
节点级复核直接空转。所以：

- AICHECK_WELDING_MATERIAL_TYPES_V2 未设或 off：包原样，什么都不变（默认）。
- stage1：加新类型、拆节点 25 的 wps_pqr、节点 24 加平台核验结果、节点 16/21 加 PMI 报告；
  焊材证明与施焊记录仍是"条件必传"（计划要求先跑一周）。
- stage2：在 stage1 之上把节点 26 焊材证明、节点 29 施焊记录改"必传"。

旧代码 wps_pqr 保留在 materialTypes 里（已绑定的资料不能失去类型），只是节点 25/29 不再要它。
翻开关前要先跑 2.4 迁移，再用 reconcile 脚本给新类型补审查点。
"""

from __future__ import annotations

import copy
import os
from typing import Any

FLAG_ENV = "AICHECK_WELDING_MATERIAL_TYPES_V2"
STAGES = ("off", "stage1", "stage2")

NEW_MATERIAL_TYPES: list[dict[str, Any]] = [
    {
        "code": "wps",
        "name": "焊接工艺规程（WPS）",
        "requiredType": "条件必传",
        "requiredFields": ["wps_no", "pqr_no", "welding_method", "material_group", "thickness_range", "approved_by"],
        "ocrProfileId": "welding_procedure_qualification_v1",
        "ocrFieldMappings": ["wps_no", "pqr_no", "welding_method", "base_material", "thickness_range", "current_range", "voltage_range", "welding_speed_range", "interpass_temperature_range", "approved_by"],
        "evidenceRequired": True,
        "splitFrom": "wps_pqr",
    },
    {
        "code": "pqr",
        "name": "焊接工艺评定报告（PQR）",
        "requiredType": "条件必传",
        "requiredFields": ["pqr_no", "welding_method", "material_group", "thickness_range", "qualification_date", "approved_by"],
        "ocrProfileId": "welding_procedure_qualification_v1",
        "ocrFieldMappings": ["report_no", "pqr_no", "welding_method", "base_material", "thickness_range", "qualification_date", "approved_by"],
        "evidenceRequired": True,
        "splitFrom": "wps_pqr",
    },
    {
        "code": "welding_process_card",
        "name": "焊接工艺卡",
        "requiredType": "条件必传",
        "requiredFields": ["wps_no", "weld_joint_type", "welding_method", "material", "specification", "parameter"],
        "ocrProfileId": "welding_procedure_qualification_v1",
        "ocrFieldMappings": ["procedure_no", "wps_no", "welding_method", "base_material", "thickness_range", "current_range", "voltage_range"],
        "evidenceRequired": True,
        "splitFrom": "wps_pqr",
    },
    {
        "code": "platform_verification",
        "name": "平台核验结果（系统自动产生）",
        "requiredType": "可选",
        "requiredFields": ["subject", "platform", "queried_at", "match_result"],
        "evidenceRequired": False,
        "systemGenerated": True,
        "replaces": "external_query_screenshot",
    },
    {
        "code": "pmi_report",
        "name": "光谱复验（PMI）报告",
        "requiredType": "条件必传",
        "requiredFields": ["report_no", "material_grade", "batch_no", "sample_count", "result"],
        "evidenceRequired": True,
        "applicabilityNote": "不锈钢、铬钼钢、镍基与钛材必传（GB/T 20801.1-2025 7.2.3 材质检查）",
    },
]

# 节点 27 的验收/烘干/领用/回收四个子表：同一资料类型下的模板，不拆成四个类型（record_kind 字段已在 OCR 映射里）
MANAGEMENT_RECORD_SUBKINDS = ["acceptance", "drying", "issue", "return"]


def stage() -> str:
    value = str(os.getenv(FLAG_ENV, "off")).strip().lower() or "off"
    return value if value in STAGES else "off"


def _requirement(node_id: int, seq: int, code: str, name: str, required_type: str, note: str, *, party: str = "施工方上传") -> dict[str, Any]:
    return {
        "id": f"REQ-{node_id}-{seq:02d}",
        "materialTypeCode": code,
        "name": name,
        "requiredType": required_type,
        "responsibleParty": party,
        "applicability": "按当前节点规则适用条件判断",
        "note": note,
    }


def _next_seq(requirements: list[dict[str, Any]]) -> int:
    seqs = []
    for item in requirements:
        tail = str(item.get("id") or "").rsplit("-", 1)[-1]
        if tail.isdigit():
            seqs.append(int(tail))
    return (max(seqs) if seqs else 0) + 1


def apply_welding_material_types_v2(pack: dict[str, Any], *, stage_name: str | None = None) -> dict[str, Any]:
    """返回变换后的新包；stage 为 off 时原样返回同一对象。"""
    current = stage_name or stage()
    if current == "off":
        return pack
    out = copy.deepcopy(pack)
    existing = {item.get("code") for item in out.get("materialTypes") or []}
    for material in NEW_MATERIAL_TYPES:
        if material["code"] not in existing:
            out.setdefault("materialTypes", []).append(copy.deepcopy(material))
    for material in out.get("materialTypes") or []:
        if material.get("code") == "welding_material_management_record":
            material["subKinds"] = list(MANAGEMENT_RECORD_SUBKINDS)

    templates = {int(item["nodeId"]): item for item in out.get("nodeTemplates") or []}

    # 节点 25：wps_pqr → wps / pqr / welding_process_card
    node25 = templates.get(25)
    if node25 is not None:
        reqs = [item for item in node25.get("requiredMaterials") or [] if item.get("materialTypeCode") != "wps_pqr"]
        seq = _next_seq(node25.get("requiredMaterials") or [])
        for code, name in (("wps", "焊接工艺规程（WPS）"), ("pqr", "焊接工艺评定报告（PQR）"), ("welding_process_card", "焊接工艺卡")):
            reqs.append(_requirement(25, seq, code, name, "条件必传", "P0 2.2：由 wps_pqr 拆出，R25 按 WPS 引用的 PQR 逐条对照。"))
            seq += 1
        node25["requiredMaterials"] = reqs

    # 节点 29：wps_pqr → wps（施焊参数只对照 WPS，不再要整份评定）
    node29 = templates.get(29)
    if node29 is not None:
        for item in node29.get("requiredMaterials") or []:
            if item.get("materialTypeCode") == "wps_pqr":
                item["materialTypeCode"] = "wps"
                item["name"] = "焊接工艺规程（WPS）"
                item["note"] = "P0 2.2：施焊参数对照 WPS；评定报告在节点 25 核。"

    # 节点 24：平台核验结果替代外部查询截图（截图降为可选，不删）
    node24 = templates.get(24)
    if node24 is not None:
        reqs = node24.get("requiredMaterials") or []
        for item in reqs:
            if item.get("materialTypeCode") == "external_query_screenshot":
                item["requiredType"] = "可选"
                item["note"] = "P0 2.2：平台核验由系统自动产生（platform_verification），截图只在平台不可用时补。"
        if not any(item.get("materialTypeCode") == "platform_verification" for item in reqs):
            reqs.append(_requirement(24, _next_seq(reqs), "platform_verification", "平台核验结果（系统自动产生）", "可选", "P0 2.2：R12 平台核实自动化的落库结果，不需要上传。", party="系统自动产生"))
        node24["requiredMaterials"] = reqs

    # 节点 16/21：光谱复验报告（不锈钢、铬钼钢条件必传）
    for node_id in (16, 21):
        node = templates.get(node_id)
        if node is None:
            continue
        reqs = node.get("requiredMaterials") or []
        if not any(item.get("materialTypeCode") == "pmi_report" for item in reqs):
            reqs.append(_requirement(node_id, _next_seq(reqs), "pmi_report", "光谱复验（PMI）报告", "条件必传", "P0 2.2：不锈钢、铬钼钢、镍基与钛材按 GB/T 20801.1-2025 7.2.3 抽查，报告必传。"))
        node["requiredMaterials"] = reqs

    if current == "stage2":
        for node_id, code in ((26, "welding_material_certificate"), (29, "welding_record"), (24, "welding_record")):
            node = templates.get(node_id)
            for item in (node or {}).get("requiredMaterials") or []:
                if item.get("materialTypeCode") == code:
                    item["requiredType"] = "必传"
                    item["note"] = (item.get("note") or "") + "（P0 2.2 stage2：改必传）"
        for material in out.get("materialTypes") or []:
            if material.get("code") in {"welding_material_certificate", "welding_record"}:
                material["requiredType"] = "必传"

    out["weldingMaterialTypesV2"] = current
    return out
