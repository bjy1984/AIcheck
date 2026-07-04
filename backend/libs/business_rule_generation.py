from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Any


GENERATED_AT = "2026-07-03 00:00:00"
STANDARD_SOURCE_ID = "KS-STANDARD-RULES"
STANDARD_SOURCE_NAME = "标准规范库（业务规则引用标准）"
STANDARD_VERSION = "rules-standards-20260703"
ALLOWED_STANDARD_EXTENSIONS = {".pdf", ".doc", ".docx", ".md", ".txt", ".yaml", ".yml", ".json"}

BUSINESS_RULE_EVIDENCE_PATTERNS = [
    r"[\u4e00-\u9fffA-Za-z0-9《》/（）()、]{0,16}(?:许可证|核准证|证书|报告|记录|方案|文件|图纸|印章|材料表|特性表|质量证明|合格证|照片|视频|铭牌|清单|报告曲线|检定证书)",
    r"(?:PQR|WPS|RT|UT|MT|PT|MTC|OCR)",
]
BUSINESS_RULE_EXTRACTION_PATTERNS = [
    r"(?:机构名称|单位名称|许可证号|证书编号|有效期|许可范围|核准项目代码|检测方法|管道级别|规格|型号|材质|批号|压力|温度|时间|保压时间|结论|签字|签章|数量|量程|精度|标准|焊缝编号|人员|日期)",
]
BUSINESS_RULE_ACTION_TERMS = ["核查", "审查", "检查", "抽查", "现场检查", "提取", "比对", "确认", "查询", "判断", "验证"]


def repo_root_from_backend() -> Path:
    return Path(__file__).resolve().parents[2]


def compact_text(value: Any, limit: int = 3000) -> str:
    text = re.sub(r"[ \t]+", " ", str(value or "").strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:limit]


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "item"


def stable_seed(*parts: Any, length: int = 10) -> str:
    return hashlib.sha1(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:length].upper()


def rule_name_from_node_ids(node_ids: list[int], node_name_by_id: dict[int, str] | None = None, fallback: str = "") -> str:
    names = []
    for node_id in node_ids:
        name = (node_name_by_id or {}).get(int(node_id), "").strip()
        if name and name not in names:
            names.append(name)
    if not names:
        return fallback
    if len(names) == 1:
        return names[0]
    return f"{names[0]}等 {len(names)} 个节点"


def split_rule_sentences(value: Any, limit: int = 12) -> list[str]:
    text = compact_text(value, 3000)
    chunks = [
        item.strip(" ；;。.\n\t")
        for item in re.split(r"[；;。\n]+", text)
        if item.strip(" ；;。.\n\t")
    ]
    return chunks[:limit]


def extract_terms(text: str, patterns: list[str], *, limit: int = 10) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            term = match.group(0).strip(" ，,；;。()（）")
            if term and term not in seen:
                seen.add(term)
                terms.append(term)
                if len(terms) >= limit:
                    return terms
    return terms


def normalize_review_class(value: Any) -> str:
    raw = compact_text(value, 20).upper().replace("类", "")
    if raw in {"A", "B", "C", "C/B", "B/C"}:
        return "C/B" if raw in {"C/B", "B/C"} else raw
    if "A" in raw:
        return "A"
    if "B" in raw and "C" in raw:
        return "C/B"
    if "B" in raw:
        return "B"
    return "C" if raw else ""


def extract_rule_field(section: str, title: str) -> str:
    marker = re.escape(title)
    pattern = rf"\*\*{marker}\*\*\s*(.*?)(?=\n\*\*|\n###\s+R\d+|\n##\s+|\Z)"
    match = re.search(pattern, section, re.S)
    return compact_text(match.group(1) if match else "")


def parse_meta_row(section: str) -> dict[str, Any]:
    row = next((line.strip() for line in section.splitlines() if line.startswith("| 来源文档")), "")
    result: dict[str, Any] = {"sourceDocument": "", "sourceSequence": None, "businessModule": "", "reviewClass": ""}
    if not row:
        return result
    for part in [item.strip() for item in row.strip("|").split("|")]:
        if part.startswith("来源文档"):
            result["sourceDocument"] = part.removeprefix("来源文档").strip()
        elif part.startswith("原位置"):
            match = re.search(r"\d+", part)
            if match:
                result["sourceSequence"] = int(match.group(0))
        elif part.startswith("业务模块"):
            result["businessModule"] = part.removeprefix("业务模块").strip()
        elif part.startswith("类别"):
            result["reviewClass"] = normalize_review_class(part.removeprefix("类别").strip())
    return result


def parse_business_rules_markdown(text: str) -> list[dict[str, Any]]:
    headings = list(re.finditer(r"^###\s+(R\d+)\s*[｜|]\s*(.+?)\s*$", text, re.M))
    rules: list[dict[str, Any]] = []
    for index, match in enumerate(headings):
        source_rule_id = match.group(1).upper()
        title = match.group(2).strip()
        section_start = match.end()
        section_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[section_start:section_end]
        meta = parse_meta_row(section)
        source_sequence = meta.get("sourceSequence") or int(source_rule_id.removeprefix("R"))
        standard_text = extract_rule_field(section, "判断准则（原文）") or extract_rule_field(section, "标准规范（原文）")
        witness_text = (
            extract_rule_field(section, "方法（原文）")
            or extract_rule_field(section, "方法及内容（原文）")
            or extract_rule_field(section, "工作见证（原文）")
        )
        agent_thinking = extract_rule_field(section, "Agent思考方式（新增）")
        toolchain_thinking = extract_rule_field(section, "工具集调用思考（新增）")
        rules.append(
            {
                "sourceRuleId": source_rule_id,
                "sourceSequence": int(source_sequence),
                "name": title,
                "inspectionItem": title,
                "inspectionCategory": meta.get("businessModule") or "",
                "businessModule": meta.get("businessModule") or "",
                "reviewClass": meta.get("reviewClass") or "C",
                "inspectionClass": meta.get("reviewClass") or "C",
                "sourceDocument": meta.get("sourceDocument") or "业务规则.md",
                "standardText": standard_text,
                "criteria": standard_text,
                "witnessText": witness_text,
                "checkMethod": witness_text,
                "agentThinking": agent_thinking,
                "toolchainThinking": toolchain_thinking,
                "rawSection": section,
            }
        )
    return rules


def parse_rule_mapping_table(text: str) -> dict[str, dict[str, Any]]:
    marker = "### 8.5 逐条规则映射"
    if marker not in text:
        return {}
    mapping_text = text.split(marker, 1)[1]
    result: dict[str, dict[str, Any]] = {}
    for line in mapping_text.splitlines():
        if not line.startswith("| R"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        rule_match = re.match(r"(R\d+)\s*(.*)", cells[0])
        if not rule_match:
            continue
        source_rule_id = rule_match.group(1).upper()
        result[source_rule_id] = {
            "thinkingModeIds": re.findall(r"M\d{2}", cells[1]),
            "toolIds": re.findall(r"T\d{2}", cells[3]),
            "keyChain": cells[2],
        }
    return result


def canonical_code(value: str) -> str:
    text = str(value or "").upper()
    text = (
        text.replace("∕", "/")
        .replace("／", "/")
        .replace("—", "-")
        .replace("－", "-")
        .replace("_", "/")
        .replace("+", "")
    )
    text = re.sub(r"\s+", "", text)
    text = text.replace("GB/T", "GBT").replace("GB/T", "GBT").replace("GB／T", "GBT")
    text = text.replace("NB/T", "NBT").replace("JB/T", "JBT").replace("SY/T", "SYT")
    text = re.sub(r"\b(GB|TSG)/(?=\d)", r"\1", text)
    text = text.replace("TSGZ", "TSGZ").replace("TSGD", "TSGD")
    text = text.replace("TSG", "TSG")
    return text


STANDARD_REF_RE = re.compile(
    r"(?:"
    r"TSG\s*[A-Z0-9]*\s*[—-]?\s*\d{4}"
    r"|GB(?:\s*/\s*T|∕T|_T|T)?\s*\+?\s*[0-9.]+(?:\s*[—-]\s*\d{4})?"
    r"|NB\s*(?:/|∕|_)?\s*T\s*[0-9.]+(?:\s*[—-]\s*\d{4})?"
    r"|NBT\s*[0-9.]+(?:\s*[—-]\s*\d{4})?"
    r"|JB\s*(?:/|∕|_)?\s*T\s*[0-9.]+(?:\s*[—-]\s*\d{4})?"
    r"|SY\s*(?:/|∕|_)?\s*T\s*[0-9.]+(?:\s*[—-]\s*\d{4})?"
    r")",
    re.I,
)


def extract_standard_refs(text: str) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for raw in STANDARD_REF_RE.findall(text or ""):
        ref = re.sub(r"\s+", " ", raw.replace("—", "-").replace("－", "-")).strip()
        key = canonical_code(ref)
        if key and key not in seen:
            seen.add(key)
            refs.append(ref)
    if "市场监管总局关于特种设备行政许可有关事项的公告" in text or "2021 年第41" in text or "2021年第41" in text:
        refs.append("市场监管总局2021年第41号公告")
    if "特种设备生产和充装单位许可规则" in text:
        refs.append("特种设备生产和充装单位许可规则")
    if "特种设备检验人员考核规则" in text:
        refs.append("特种设备检验人员考核规则")
    return refs


def list_standard_files(standards_root: Path, *, workspace_root: Path | None = None) -> list[dict[str, Any]]:
    root = standards_root
    workspace = workspace_root or standards_root.parents[1]
    files: list[dict[str, Any]] = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if not path.is_file() or path.name.startswith(".") or path.suffix.lower() not in ALLOWED_STANDARD_EXTENSIONS:
            continue
        relative = path.relative_to(workspace).as_posix()
        try:
            data = path.read_bytes()
            file_hash = hashlib.sha256(data).hexdigest()
            size = len(data)
        except OSError:
            file_hash = ""
            size = 0
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        files.append(
            {
                "path": path,
                "relativePath": relative,
                "relativeToStandards": path.relative_to(root).as_posix(),
                "fileName": path.name,
                "fileSize": size,
                "hash": file_hash,
                "contentType": content_type,
                "codes": file_codes(path.name),
            }
        )
    return sorted(files, key=lambda item: item["relativePath"].lower())


def file_codes(file_name: str) -> list[str]:
    codes = [canonical_code(match) for match in STANDARD_REF_RE.findall(file_name)]
    name = canonical_code(file_name)
    extra: list[str] = []
    if "2021" in file_name and "41" in file_name and "公告" in file_name:
        extra.append("市场监管总局2021年第41号公告")
    if "特种设备生产和充装单位许可规则" in file_name:
        extra.extend(["特种设备生产和充装单位许可规则", "TSG07-2019"])
    if "特种设备检验人员考核规则" in file_name:
        extra.append("特种设备检验人员考核规则")
    if "NB_T_47013" in file_name or "47013" in name:
        extra.append("NBT47013")
    return sorted({code for code in [*codes, *extra] if code})


def match_standard_files(refs: list[str], standard_files: list[dict[str, Any]]) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        ref_key = canonical_code(ref)
        for file in standard_files:
            file_keys = set(file.get("codes") or [])
            file_key_blob = canonical_code(file.get("relativeToStandards") or file.get("fileName") or "")
            matched = False
            if ref in file_keys or ref_key in file_keys:
                matched = True
            elif ref_key and any(ref_key == key or key.startswith(ref_key) or ref_key.startswith(key) for key in file_keys):
                matched = True
            elif ref_key == "NBT47013" and "NB_T_47013_SPLIT" in file_key_blob:
                matched = True
            elif ref_key and ref_key in file_key_blob:
                matched = True
            if matched:
                key = (ref, file["relativePath"])
                if key in seen:
                    continue
                seen.add(key)
                matches.append({"reference": ref, "file": file["relativePath"], "fileName": file["fileName"]})
    return matches


def severity_for_review_class(review_class: str) -> str:
    if "A" in review_class:
        return "high"
    if "B" in review_class:
        return "medium"
    return "low"


def compile_ai_execution(rule: dict[str, Any]) -> dict[str, Any]:
    standard_text = compact_text(rule.get("standardText") or rule.get("criteria"), 3000)
    witness_text = compact_text(rule.get("witnessText") or rule.get("checkMethod"), 3000)
    agent_thinking = compact_text(rule.get("agentThinking"), 3000)
    toolchain_thinking = compact_text(rule.get("toolchainThinking"), 3000)
    combined = "\n".join(
        part for part in [standard_text, witness_text, agent_thinking, toolchain_thinking] if part
    )
    method_sentences = split_rule_sentences(
        witness_text or agent_thinking or toolchain_thinking,
        limit=20,
    )
    standard_sentences = split_rule_sentences(standard_text, limit=12)
    action_steps = [
        sentence
        for sentence in method_sentences
        if any(term in sentence for term in BUSINESS_RULE_ACTION_TERMS) or sentence.startswith(("是否", "需", "应"))
    ] or method_sentences[:6]
    acceptance_criteria = [
        sentence
        for sentence in method_sentences + standard_sentences
        if any(term in sentence for term in ["是否", "不得", "不应", "应当", "应", "符合", "覆盖", "一致", "有效", "合格", "不少于", "不低于", "范围"])
    ][:10]
    required_evidence = extract_terms(combined, BUSINESS_RULE_EVIDENCE_PATTERNS, limit=12) or method_sentences[:3]
    extraction_targets = extract_terms(combined, BUSINESS_RULE_EXTRACTION_PATTERNS, limit=16)
    human_confirmation = []
    if rule.get("inspectionClass") == "A" or rule.get("reviewClass") == "A":
        human_confirmation.append("A 类监检项目发布或审查结论需人工确认。")
    if any(term in witness_text for term in ["现场", "抽查", "照片", "视频", "目视", "实物"]):
        human_confirmation.append("涉及现场检查、抽查或影像证据时，AI 只做辅助核验，需监检人员确认现场事实。")
    if any(term in witness_text for term in ["如果不能", "必要时", "缺少", "不足", "不一致", "不能覆盖"]):
        human_confirmation.append("证据缺失、范围不覆盖或跨文件不一致时生成补充资料项或联络单。")
    return {
        "schemaVersion": "business-rule-execution-v1",
        "compiledAt": GENERATED_AT,
        "sourceFields": {
            "sourceRuleId": rule.get("sourceRuleId"),
            "sourceDocument": rule.get("sourceDocument"),
            "sequence": rule.get("sourceSequence"),
            "inspectionCategory": rule.get("inspectionCategory") or rule.get("businessModule"),
            "inspectionItem": rule.get("inspectionItem") or rule.get("name"),
            "inspectionClass": rule.get("inspectionClass") or rule.get("reviewClass"),
            "standardText": standard_text,
            "witnessText": witness_text,
            "agentThinking": agent_thinking,
            "toolchainThinking": toolchain_thinking,
        },
        "requiredEvidence": required_evidence,
        "extractionTargets": extraction_targets,
        "verificationSteps": action_steps[:10],
        "acceptanceCriteria": acceptance_criteria,
        "humanConfirmation": human_confirmation or ["证据不足、OCR 置信度不足或结论影响放行时需人工确认。"],
        "promptContext": compact_text(
            "\n".join(
                [
                    f"监检项目：{rule.get('inspectionItem') or rule.get('name')}",
                    f"类别：{rule.get('inspectionClass') or rule.get('reviewClass') or '-'}",
                    f"判断准则/标准规范：{standard_text or '-'}",
                    f"方法及内容/工作见证：{witness_text or '-'}",
                    f"Agent思考方式：{agent_thinking or '-'}",
                    f"工具集调用思考：{toolchain_thinking or '-'}",
                ]
            ),
            1600,
        ),
    }


def build_rule_sets(
    markdown_text: str,
    *,
    standard_files: list[dict[str, Any]],
    existing_rules_by_source: dict[str, dict[str, Any]] | None = None,
    node_name_by_id: dict[int, str] | None = None,
    import_version: str = "v2026.07.03",
) -> list[dict[str, Any]]:
    mapping = parse_rule_mapping_table(markdown_text)
    existing = existing_rules_by_source or {}
    rule_sets: list[dict[str, Any]] = []
    for parsed in parse_business_rules_markdown(markdown_text):
        source_rule_id = parsed["sourceRuleId"]
        old = existing.get(source_rule_id) or {}
        rule_number = int(source_rule_id.removeprefix("R"))
        rule_key = old.get("ruleKey") or f"engineering-inspection-r{rule_number:02d}"
        node_ids = old.get("nodeIds") or [parsed["sourceSequence"]]
        display_name = rule_name_from_node_ids(
            [int(item) for item in node_ids if str(item).isdigit()],
            node_name_by_id,
            parsed["name"],
        )
        refs = extract_standard_refs("\n".join([parsed.get("standardText", ""), parsed.get("witnessText", "")]))
        standard_matches = match_standard_files(refs, standard_files)
        rule = {
            "id": old.get("id") or f"RULE-ENG-INSP-R{rule_number:02d}",
            "name": display_name,
            "ruleKey": rule_key,
            "version": f"{rule_key}-{import_version}",
            "status": "已发布",
            "nodeIds": node_ids,
            "severity": severity_for_review_class(parsed["reviewClass"]),
            "reviewClass": parsed["reviewClass"],
            "inspectionClass": parsed["inspectionClass"],
            "promptVersion": old.get("promptVersion") or f"prompt-engineering-inspection-{import_version}",
            "outputSchemaVersion": old.get("outputSchemaVersion") or "schema-review-v1.3",
            "sourceRuleId": source_rule_id,
            "sourceDocument": parsed["sourceDocument"],
            "sourceSequence": parsed["sourceSequence"],
            "businessModule": parsed["businessModule"],
            "inspectionCategory": parsed["inspectionCategory"],
            "inspectionItem": parsed["inspectionItem"],
            "materialTypeCodes": old.get("materialTypeCodes") or ["generic_review_material"],
            "thinkingModeIds": mapping.get(source_rule_id, {}).get("thinkingModeIds") or old.get("thinkingModeIds") or [],
            "toolIds": mapping.get(source_rule_id, {}).get("toolIds") or old.get("toolIds") or [],
            "criteria": parsed["standardText"],
            "standardText": parsed["standardText"],
            "checkMethod": parsed["witnessText"],
            "witnessText": parsed["witnessText"],
            "sourceWitness": old.get("sourceWitness") or "",
            "agentThinking": parsed["agentThinking"],
            "toolchainThinking": parsed["toolchainThinking"],
            "referencedStandards": standard_matches,
        }
        rule["aiExecution"] = compile_ai_execution(rule)
        rule_sets.append(rule)
    return rule_sets


def build_standard_documents_seed(
    standard_files: list[dict[str, Any]],
    *,
    source_id: str = STANDARD_SOURCE_ID,
    source_name: str = STANDARD_SOURCE_NAME,
) -> dict[str, list[dict[str, Any]]]:
    documents: list[dict[str, Any]] = []
    versions: list[dict[str, Any]] = []
    knowledge_files: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    for file in standard_files:
        seed = stable_seed(source_id, file["relativePath"])
        document_id = f"KDOC-{seed}"
        version_id = f"KDV-{seed}-V1"
        file_id = f"KF-KB-{seed}"
        file_type = Path(file["fileName"]).suffix.lower().lstrip(".") or file.get("contentType") or "file"
        documents.append(
            {
                "id": document_id,
                "projectId": None,
                "businessPackId": "engineering_inspection_v1",
                "materialTypeCode": "standard_reference",
                "fileName": file["fileName"],
                "originalFileName": file["fileName"],
                "fileType": file_type,
                "sourceOrgName": source_name,
                "contextDescription": f"来自 {file['relativePath']}；按 rules/业务规则.md 引用标准整理入库。",
                "uploaderName": "知识库管理员",
                "currentVersionId": version_id,
                "fileStatus": "已上传",
                "currentOcrStatus": "待识别",
                "updatedAt": GENERATED_AT,
                "actions": ["file:view", "file:preview", "file:download"],
            }
        )
        versions.append(
            {
                "id": version_id,
                "documentId": document_id,
                "versionNo": "V1",
                "hash": file.get("hash") or "",
                "fileSize": int(file.get("fileSize") or 0),
                "fileName": file["fileName"],
                "originalFileName": file["fileName"],
                "contextDescription": f"来自 {file['relativePath']}；按 rules/业务规则.md 引用标准整理入库。",
                "storageKey": f"local://{file['relativePath']}",
                "storageBucket": "local",
                "ocrStatus": "待识别",
                "sliceStatus": "未切片",
                "vectorStatus": "待向量化",
                "uploaderName": "知识库管理员",
                "uploadTime": GENERATED_AT,
                "isCurrent": True,
            }
        )
        knowledge_files.append(
            {
                "id": file_id,
                "fileName": file["fileName"],
                "originalFileName": file["fileName"],
                "sourceId": source_id,
                "sourceName": source_name,
                "sourceType": "standard",
                "contextDescription": f"来自 {file['relativePath']}；按 rules/业务规则.md 引用标准整理入库。",
                "projectId": None,
                "projectName": "",
                "nodeId": None,
                "nodeName": "",
                "documentId": document_id,
                "documentVersionId": version_id,
                "ocrStatus": "待识别",
                "sliceStatus": "未切片",
                "vectorStatus": "待向量化",
                "chunkCount": 0,
                "vectorCount": 0,
                "updatedAt": GENERATED_AT,
                "sourceRelativePath": file["relativePath"],
                "actions": ["knowledge:view", "knowledge:reindex"],
            }
        )
        tasks.append(
            {
                "id": f"KT-{seed}",
                "taskType": "ocr",
                "targetType": "file",
                "targetId": file_id,
                "targetName": file["fileName"],
                "documentId": document_id,
                "documentVersionId": version_id,
                "projectId": None,
                "nodeId": None,
                "status": "排队中",
                "progress": 0,
                "createdAt": GENERATED_AT,
                "updatedAt": GENERATED_AT,
                "revision": 1,
                "actions": ["knowledge:task-retry"],
            }
        )
    return {"documents": documents, "versions": versions, "knowledgeFiles": knowledge_files, "knowledgeTasks": tasks}


def build_standard_anchor_clauses(rule_sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def related(*rule_ids: str) -> list[dict[str, Any]]:
        wanted = set(rule_ids)
        return [rule for rule in rule_sets if rule.get("sourceRuleId") in wanted]

    anchors = [
        {
            "clauseId": "TSG-Z6002-3.2",
            "clauseNo": "3.2",
            "title": "焊工资格覆盖要求",
            "rules": related("R12", "R17"),
            "sectionPath": ["TSG Z6002-2010 焊接人员考核细则", "焊工资格覆盖"],
            "nodeIds": [24, 29],
            "materialTypes": ["welder_certificate", "welding_record"],
            "tags": ["焊工", "资格证", "持证项目", "有效期"],
        },
        {
            "clauseId": "TSG-D7006-D2.4.1",
            "clauseNo": "D2.4.1",
            "title": "压力管道元件质量证明与验收要求",
            "rules": related("R59", "R61", "R62", "R63", "R64", "R65"),
            "sectionPath": ["TSG D7006-2020 压力管道监督检验规则", "附件 D", "D2.4.1 压力管道元件及安全附件"],
            "nodeIds": [14, 16, 17, 18, 19, 20],
            "materialTypes": ["quality_certificate", "material_retest_report"],
            "tags": ["质量证明书", "材料牌号", "炉批号", "盖章"],
        },
        {
            "clauseId": "NB-T-47013-NDT-REPORT",
            "clauseNo": "报告",
            "title": "无损检测记录、报告和底片审查要求",
            "rules": related("R28", "R29", "R30", "R53"),
            "sectionPath": ["NB/T 47013 承压设备无损检测", "检测记录与报告"],
            "nodeIds": [40, 41, 42, 65],
            "materialTypes": ["ndt_report", "radiographic_film"],
            "tags": ["无损检测", "检测报告", "焊口编号", "签章", "底片"],
        },
    ]
    clauses: list[dict[str, Any]] = []
    for anchor in anchors:
        text_parts = []
        linked_file_id = None
        linked_version_id = None
        for rule in anchor["rules"]:
            text_parts.append(f"{rule.get('sourceRuleId')} {rule.get('name')}：{rule.get('standardText') or rule.get('witnessText')}")
            if not linked_file_id:
                match = next(iter(rule.get("referencedStandards") or []), {})
                if match.get("file"):
                    seed = stable_seed(STANDARD_SOURCE_ID, match["file"])
                    linked_file_id = f"KF-KB-{seed}"
                    linked_version_id = f"KDV-{seed}-V1"
        clauses.append(
            {
                "id": f"KC-{anchor['clauseId']}",
                "clauseId": anchor["clauseId"],
                "kbDocId": STANDARD_SOURCE_ID,
                "kbVersion": STANDARD_VERSION,
                "clauseNo": anchor["clauseNo"],
                "title": anchor["title"],
                "text": compact_text("\n".join(text_parts), 1200),
                "pageNo": anchor["nodeIds"][0],
                "bbox": [80, 160, 1180, 760],
                "sectionPath": anchor["sectionPath"],
                "scope": {
                    "businessPackId": "engineering_inspection_v1",
                    "nodeIds": anchor["nodeIds"],
                    "materialTypes": anchor["materialTypes"],
                },
                "tags": anchor["tags"],
                "status": "effective",
                "fileId": linked_file_id,
                "documentVersionId": linked_version_id,
            }
        )
    return clauses


def build_rule_reference_clauses(rule_sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    for rule in rule_sets:
        match = next(iter(rule.get("referencedStandards") or []), {})
        file_id = f"KF-KB-{stable_seed(STANDARD_SOURCE_ID, match['file'])}" if match.get("file") else None
        version_id = f"KDV-{stable_seed(STANDARD_SOURCE_ID, match['file'])}-V1" if match.get("file") else None
        clauses.append(
            {
                "id": f"KC-{rule['sourceRuleId']}",
                "clauseId": f"BUSINESS-RULE-{rule['sourceRuleId']}",
                "kbDocId": STANDARD_SOURCE_ID,
                "kbVersion": STANDARD_VERSION,
                "clauseNo": rule["sourceRuleId"],
                "title": rule["name"],
                "text": compact_text("\n".join([rule.get("standardText") or "", rule.get("witnessText") or ""]), 1000),
                "pageNo": int(rule.get("sourceSequence") or 1),
                "bbox": [80, 160, 1180, 760],
                "sectionPath": ["业务规则.md", rule.get("businessModule") or "业务规则", rule["name"]],
                "scope": {
                    "businessPackId": "engineering_inspection_v1",
                    "nodeIds": rule.get("nodeIds") or [],
                    "materialTypes": rule.get("materialTypeCodes") or [],
                },
                "tags": [rule.get("sourceRuleId"), rule.get("reviewClass"), *(rule.get("thinkingModeIds") or [])],
                "status": "effective",
                "fileId": file_id,
                "documentVersionId": version_id,
            }
        )
    return clauses


def build_page_index_nodes(clauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchor_by_id = {item["clauseId"]: item for item in clauses}
    root_children = ["PIN-TSG-Z6002-3", "PIN-TSG-D7006-D2", "PIN-NB-T-47013-NDT"]
    return [
        {
            "id": "PIN-RULE-STANDARDS-ROOT",
            "pageIndexNodeId": "PIN-RULE-STANDARDS-ROOT",
            "kbDocId": STANDARD_SOURCE_ID,
            "kbVersion": STANDARD_VERSION,
            "nodeId": "root",
            "parentNodeId": None,
            "title": "业务规则引用标准规范总览",
            "summary": "覆盖 rules/standards 中由业务规则引用的 TSG、GB、NB/T、JB/T、SY/T 标准规范及公告文件。",
            "startPage": 1,
            "endPage": 90,
            "sectionPath": ["业务规则引用标准规范库"],
            "children": root_children,
            "linkedClauseIds": ["TSG-Z6002-3.2", "TSG-D7006-D2.4.1", "NB-T-47013-NDT-REPORT"],
            "businessPackId": "engineering_inspection_v1",
            "nodeTypes": ["inspection_review"],
            "materialTypes": ["welder_certificate", "quality_certificate", "ndt_report"],
            "tags": ["监督检验", "资料审查", "正文", "附录", "跨章节"],
            "status": "effective",
        },
        {
            "id": "PIN-TSG-Z6002-3",
            "pageIndexNodeId": "PIN-TSG-Z6002-3",
            "kbDocId": STANDARD_SOURCE_ID,
            "kbVersion": STANDARD_VERSION,
            "nodeId": "3",
            "parentNodeId": "PIN-RULE-STANDARDS-ROOT",
            "title": "TSG Z6002 焊工资格覆盖",
            "summary": (anchor_by_id.get("TSG-Z6002-3.2") or {}).get("text", "")[:160],
            "startPage": 24,
            "endPage": 29,
            "sectionPath": ["TSG Z6002-2010 焊接人员考核细则", "焊工资格覆盖"],
            "children": [],
            "linkedClauseIds": ["TSG-Z6002-3.2"],
            "businessPackId": "engineering_inspection_v1",
            "nodeTypes": ["welder_certificate_review"],
            "materialTypes": ["welder_certificate", "welding_record"],
            "tags": ["焊工", "资格证", "有效期", "持证项目"],
            "status": "effective",
        },
        {
            "id": "PIN-TSG-D7006-D2",
            "pageIndexNodeId": "PIN-TSG-D7006-D2",
            "kbDocId": STANDARD_SOURCE_ID,
            "kbVersion": STANDARD_VERSION,
            "nodeId": "D2",
            "parentNodeId": "PIN-RULE-STANDARDS-ROOT",
            "title": "TSG D7006 压力管道元件资料",
            "summary": (anchor_by_id.get("TSG-D7006-D2.4.1") or {}).get("text", "")[:160],
            "startPage": 12,
            "endPage": 23,
            "sectionPath": ["TSG D7006-2020 压力管道监督检验规则", "附件 D"],
            "children": [],
            "linkedClauseIds": ["TSG-D7006-D2.4.1"],
            "businessPackId": "engineering_inspection_v1",
            "nodeTypes": ["material_review"],
            "materialTypes": ["quality_certificate", "material_retest_report"],
            "tags": ["质量证明书", "材料牌号", "炉批号", "盖章"],
            "status": "effective",
        },
        {
            "id": "PIN-NB-T-47013-NDT",
            "pageIndexNodeId": "PIN-NB-T-47013-NDT",
            "kbDocId": STANDARD_SOURCE_ID,
            "kbVersion": STANDARD_VERSION,
            "nodeId": "NDT",
            "parentNodeId": "PIN-RULE-STANDARDS-ROOT",
            "title": "NB/T 47013 无损检测报告",
            "summary": "正文和附录跨章节说明无损检测报告签章要求；"
            + (anchor_by_id.get("NB-T-47013-NDT-REPORT") or {}).get("text", "")[:160],
            "startPage": 35,
            "endPage": 65,
            "sectionPath": ["NB/T 47013 承压设备无损检测", "检测记录与报告"],
            "children": [],
            "linkedClauseIds": ["NB-T-47013-NDT-REPORT"],
            "businessPackId": "engineering_inspection_v1",
            "nodeTypes": ["ndt_review"],
            "materialTypes": ["ndt_report", "radiographic_film"],
            "tags": ["无损检测", "检测报告", "签章", "附录", "跨章节"],
            "status": "effective",
        },
    ]


def build_retrieval_traces(clauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary = next((item for item in clauses if item.get("clauseId") == "TSG-Z6002-3.2"), clauses[0] if clauses else {})
    return [
        {
            "id": "RTR-KB-SCORECARD-001",
            "retrievalTraceId": "RTR-KB-SCORECARD-001",
            "reviewRunId": "RRUN-KB-SCORECARD-SEED",
            "query": "焊工资格证有效期如何校验？",
            "queryType": "knowledge_scorecard_seed",
            "routerVersion": "knowledge-router-v1",
            "selectedRoute": "hybrid_review_basis_search",
            "routerSignals": {"exactClauseRefs": [], "needsPageIndex": False, "tokenCount": 4, "queryLength": 13},
            "queryRouter": {
                "selectedRoute": "hybrid_review_basis_search",
                "signals": {"exactClauseRefs": [], "needsPageIndex": False, "tokenCount": 4, "queryLength": 13},
                "fallbackRoute": "hybrid_review_basis_search",
            },
            "filters": {"businessPackId": "engineering_inspection_v1", "nodeId": 24, "effectiveAt": GENERATED_AT},
            "retrievers": [
                {"type": "exact_clause_lookup", "enabled": False, "clauseRefs": []},
                {"type": "clause_index", "topK": 3, "candidateCount": len(clauses)},
                {"type": "hybrid_bm25_dense", "topK": 3, "implementation": "local_token_overlap_until_vector_index"},
                {"type": "pageindex_tree", "enabled": False, "implementation": "local_page_index_nodes", "candidateNodeCount": 4, "selectedNodeCount": 0},
            ],
            "pageIndexTree": {"candidateNodeCount": 4, "selectedNodes": [], "linkedClauseIds": [], "treeSearchPath": []},
            "selectedClauses": [{**primary, "score": 2.0, "retrievalMode": "hybrid_bm25_dense_local"}] if primary else [],
            "kbVersion": STANDARD_VERSION,
            "createdAt": GENERATED_AT,
        }
    ]


def build_standard_knowledge_seed(
    standard_files: list[dict[str, Any]],
    rule_sets: list[dict[str, Any]],
) -> dict[str, Any]:
    file_seed = build_standard_documents_seed(standard_files)
    anchor_clauses = build_standard_anchor_clauses(rule_sets)
    rule_clauses = build_rule_reference_clauses(rule_sets)
    clauses = [*anchor_clauses, *rule_clauses]
    return {
        **file_seed,
        "source": {
            "id": STANDARD_SOURCE_ID,
            "name": STANDARD_SOURCE_NAME,
            "sourceType": "standard",
            "version": STANDARD_VERSION,
            "status": "启用",
            "fileCount": len(standard_files),
            "chunkCount": 0,
            "vectorStatus": "待向量化",
            "updatedAt": GENERATED_AT,
            "actions": ["knowledge:view", "knowledge:manage", "knowledge:reindex"],
        },
        "clauses": clauses,
        "pageIndexNodes": build_page_index_nodes(anchor_clauses),
        "retrievalTraces": build_retrieval_traces(anchor_clauses),
    }


def render_standard_match_section(standard_files: list[dict[str, Any]], rule_sets: list[dict[str, Any]]) -> str:
    refs_by_file: dict[str, set[str]] = {file["relativePath"]: set() for file in standard_files}
    rules_by_file: dict[str, set[str]] = {file["relativePath"]: set() for file in standard_files}
    for rule in rule_sets:
        for match in rule.get("referencedStandards") or []:
            file = match.get("file")
            if not file:
                continue
            refs_by_file.setdefault(file, set()).add(match.get("reference") or "")
            rules_by_file.setdefault(file, set()).add(rule.get("sourceRuleId") or "")
    rows = [
        "## 标准规范文件匹配索引",
        "",
        "> 自动生成：根据本文件各条业务规则的“判断准则/标准规范”和 `rules/standards` 实际文件清单匹配。未在规则中命中的文件仍作为标准规范库候选入库，后续 OCR/切片后可用于扩展检索。",
        "",
        "| 序号 | 标准规范文件 | 命中规则 | 匹配引用 |",
        "| --- | --- | --- | --- |",
    ]
    for index, file in enumerate(standard_files, start=1):
        rules = "、".join(sorted(item for item in rules_by_file.get(file["relativePath"], set()) if item)) or "候选"
        refs = "；".join(sorted(item for item in refs_by_file.get(file["relativePath"], set()) if item)) or "-"
        rows.append(f"| {index} | `{file['relativePath']}` | {rules} | {refs} |")
    return "\n".join(rows).strip() + "\n"


def replace_generated_standard_section(markdown_text: str, section: str) -> str:
    title = "## 标准规范文件匹配索引"
    if title in markdown_text:
        return re.sub(r"## 标准规范文件匹配索引\n.*?(?=\n##\s+引用索引)", section, markdown_text, flags=re.S)
    marker = "\n## 引用索引"
    if marker in markdown_text:
        return markdown_text.replace(marker, f"\n{section}\n{marker}", 1)
    return markdown_text.rstrip() + "\n\n" + section
