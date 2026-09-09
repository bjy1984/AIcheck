"""Source-only NDT procedure extraction; no synthetic review identities or findings."""
import re
from copy import deepcopy

PROFILE_ID = "ndt_procedure_v1"
LABELS = {
    "procedure_no": ["文件编号", "工艺规程编号", "操作指导书编号"],
    "procedure_revision": ["文件版本", "版次"],
    "organization_name": ["检测单位", "编制单位"],
    "document_kind": ["文件类型"],
    "method": ["检测方法"],
    "standard_no": ["执行标准", "依据标准"],
    "referenced_procedure_no": ["引用规程编号", "依据规程编号"],
    "referenced_procedure_revision": ["引用规程版本", "依据规程版本"],
    "equipment": ["检测设备"], "sensitivity": ["检测灵敏度"],
    "acceptance_level": ["验收级别"], "removal_method": ["渗透剂去除方法"],
    "emulsifier_application": ["乳化剂施加方法"],
    "application_status": ["应用状态"],
}


def make_profile(structured_config, preprocess_policy):
    return {
        "profileId": PROFILE_ID, "documentType": "ndt_procedure",
        "postprocessVersion": "ndt-procedure-explicit-labels-v1",
        "requiredFields": ["procedure_no", "procedure_revision", "method", "standard_no"],
        "requiredTables": [], "fieldLabels": deepcopy(LABELS),
        "sealRules": {"required": False, "expectedSealTypes": []},
        "qualityRules": {"minFieldConfidence": .75, "criticalConflictFields": ["procedure_no", "procedure_revision", "method", "standard_no"]},
        "preprocessPolicy": deepcopy(preprocess_policy),
        "structuredExtraction": structured_config(PROFILE_ID, list(LABELS), field_definitions={
            "procedure_no": "本文件自己的编号；不得用引用规程编号或文件名填充。",
            "procedure_revision": "本文件明确版次；不得用引用规程版本、上传次数或日期猜测。",
            "document_kind": "只按原文识别工艺规程或操作指导书，不能仅凭材料类型ndt_procedure判断。",
            "referenced_procedure_no": "本文件引用的规程编号，与本文件自己的编号分开。",
            "referenced_procedure_revision": "引用关系中明确指定的规程版本，未写不得补为当前版本。",
            "organization_name": "原文机构名称；不生成organizationId、projectId或其他系统身份。",
            "emulsifier_application": "本次工艺明确采用的乳化剂施加方式；不得把标准列举的允许方式当作实用方式。",
            "removal_method": "原文采用的去除方式，不由检测方法PT推断具体A/B/C/D。",
            "application_status": "仅提取原文明示的应用状态，缺记录不代表尚未应用，不生成complete、人工核验或零应用声明。",
        }),
    }


def extract_explicit_fields(result, append_field, *, field_labels=None, conflict_code="NDT_PROCEDURE_LABEL_CONFLICT"):
    for code, labels in (LABELS if field_labels is None else field_labels).items():
        existing = [row for row in result.get("fields", []) if isinstance(row, dict) and row.get("fieldCode") == code]
        candidates = {}
        pattern = re.compile(r"^(?:" + "|".join(re.escape(label) for label in labels) + r")\s*[:：]\s*(\S.*?)\s*$")
        for fragment in result.get("fragments", []) or []:
            if not isinstance(fragment, dict) or not isinstance(fragment.get("text"), str):
                continue
            for line in fragment["text"].splitlines():
                match = pattern.fullmatch(line.strip())
                if match and len(match[1]) <= 160:
                    candidates.setdefault(match[1], {"text": match[1], "fragment": fragment})
        conflict = len(candidates) > 1 or bool(candidates and any(row.get("fieldValue") not in list(candidates) for row in existing))
        if conflict:
            for row in existing:
                row["qualityFlags"] = sorted({*(row.get("qualityFlags") or []), "field_value_conflict"})
            result.setdefault("diagnostics", []).append({"code": conflict_code, "level": "warning",
                "message": "同一字段出现多个不同值，需核对原文。", "fieldCode": code})
        elif len(candidates) == 1 and not existing:
            append_field(result, code, labels[0], next(iter(candidates.values())))
