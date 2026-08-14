from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.db.repository import load_state, repo
from libs.db.seed import DEFAULT_BUSINESS_PACK_ID, STANDARD_RULES_SOURCE_ID
from libs.knowledge_indexing import QWEN3_EMBEDDING_MODEL, QWEN3_INDEX_VERSION, noise_like_text
from libs.knowledge_retrieval import retrieve_knowledge_clauses

GOLDEN_CASES: list[dict[str, str]] = [
    {"question": "压力管道监督检验规则的监督检验范围如何引用？", "path": "TSG D7006-2020"},
    {"question": "非合金钢焊条验收和型号应引用哪个标准？", "path": "GBT 5117-2012"},
    {"question": "特种设备检验机构核准相关要求引用 TSG Z7002。", "path": "TSG Z7002"},
    {"question": "NB/T 47013.8-2025 泄漏检测附录和正文如何关联？", "path": "47013.8-2025"},
    {"question": "气体保护电弧焊实心焊丝材料验收依据是什么？", "path": "8110-2020"},
    {"question": "低中压锅炉用无缝钢管验收应查哪个标准？", "path": "3087-2022"},
    {"question": "压力管道规范工业管道总则如何引用 GB/T 20801.1？", "path": "20801.1-2025"},
    {"question": "输送流体用无缝钢管质量证明书应引用什么标准？", "path": "8163-2018"},
    {"question": "特种设备行政许可事项公告 2021 年 41 号如何作为依据？", "path": "2021年41号"},
    {"question": "高压锅炉用无缝钢管验收引用 GB/T 5310。", "path": "5310-2023"},
    {"question": "油气输送管道跨越工程施工规范的验收依据是什么？", "path": "50460-2015"},
    {"question": "埋地钢质管道腐蚀防护工程检验应查 GB/T 19285。", "path": "19285-2026"},
    {"question": "钢制对焊管件类型与参数应引用 GB/T 12459。", "path": "12459-2025"},
    {"question": "NB/T 47013.17-2024 磁记忆检测的适用范围是什么？", "path": "47013.17-2024"},
    {"question": "NB/T 47013.7-2012 目视检测报告要求如何引用？", "path": "47013.7-2012"},
    {"question": "NB/T 47013.6-2015 涡流检测验收等级如何查？", "path": "47013.6-2015"},
    {"question": "NB/T 47013.16-2024 红外热成像检测应引用哪个文件？", "path": "47013.16-2024"},
    {"question": "NB/T 47013.3-2023 超声检测报告章节和验收要求。", "path": "47013.3-2023"},
    {"question": "NB/T 47013.14-2023 射线计算机辅助成像检测依据。", "path": "47013.14-2023"},
    {"question": "NB/T 47013.11-2023 射线数字成像检测报告要求。", "path": "47013.11-2023"},
    {"question": "NB/T 47013.18-2024 阵列涡流检测引用依据。", "path": "47013.18-2024"},
    {"question": "NB/T 47013.2-2015 射线检测底片质量和报告要求。", "path": "47013.2-2015"},
    {"question": "NB/T 47013.1-2015 通用要求适用于哪些无损检测方法？", "path": "47013.1-2015"},
    {"question": "NB/T 47013.5-2015 渗透检测验收和报告要求。", "path": "47013.5-2015"},
    {"question": "NB/T 47013.12-2015 漏磁检测如何引用？", "path": "47013.12-2015"},
    {"question": "NB/T 47013.13-2015 脉冲涡流检测适用范围。", "path": "47013.13-2015"},
    {"question": "NB/T 47013.10-2015 TOFD 超声检测报告依据。", "path": "47013.10-2015"},
    {"question": "NB/T 47013.15-2021 相控阵超声检测验收要求。", "path": "47013.15-2021"},
    {"question": "旧版 NB/T 47013.8-2012 泄漏检测什么时候才应引用？", "path": "47013.8-2012"},
    {"question": "NB/T 47013.9-2012 声发射检测报告要求。", "path": "47013.9-2012"},
    {"question": "NB/T 47013.4-2015 磁粉检测验收依据。", "path": "47013.4-2015"},
    {"question": "石化和化工装置用无缝钢管应引用 GB/T 9948。", "path": "9948-2025"},
    {"question": "钢制对焊管件技术规范 GB/T 13401 如何引用？", "path": "13401-2025"},
    {"question": "埋地钢质管道阴极保护技术规范 GB/T 21448 的检查点。", "path": "21448-2017"},
    {"question": "NB/T 47013-2015 承压设备无损检测合集如何作为旧版依据？", "path": "47013-2015"},
    {"question": "工业金属管道工程施工质量验收规范 GB 50184。", "path": "50184-2011"},
    {"question": "阀门的检验和试验应引用 GB/T 26480。", "path": "26480-2011"},
    {"question": "输送流体用不锈钢无缝钢管 GB/T 14976 验收。", "path": "14976-2025"},
    {"question": "工业阀门压力试验 GB/T 13927 如何作为审计依据？", "path": "13927-2022"},
    {"question": "防腐层漏点检测 SY/T 4113.11-2023 的方法依据。", "path": "4113.11—2023"},
    {"question": "承压类特种设备安全附件安全技术规程 TSG 92-2026。", "path": "92—2026"},
    {"question": "工业金属管道工程施工规范 GB 50235。", "path": "50235-2010"},
    {"question": "焊接材料质量管理规程 JB/T 3223 的审计依据。", "path": "3223-2017"},
    {"question": "承压设备用焊接材料订货技术条件 NB/T 47018。", "path": "47018-2017"},
    {"question": "压力管道元件型式试验或许可相关 TSG31-2025。", "path": "TSG31-2025"},
    {"question": "特种设备生产和充装单位许可规则 TSG 07-2019。", "path": "TSG 07-2019"},
    {"question": "现场设备工业管道焊接工程施工规范 GB 50236。", "path": "50236-2011"},
    {"question": "特种设备检验人员考核规则如何引用？", "path": "特种设备检验人员考核规则"},
    {"question": "阴极保护技术条件 GB/T 33378-2025 审查依据。", "path": "33378-2025"},
    {"question": "承压设备焊接工艺评定 NB/T 47014-2023。", "path": "47014-2023"},
    {"question": "低中压锅炉管验收依据。", "path": "3087-2022"},
    {"question": "锅炉管质量证明书看哪个标准？", "path": "3087-2022"},
    {"question": "高压锅炉管验收依据。", "path": "5310-2023"},
    {"question": "高压锅炉用钢管质量证明书。", "path": "5310-2023"},
    {"question": "实心焊丝验收依据。", "path": "8110-2020"},
    {"question": "熔化极气体保护焊丝查什么规范？", "path": "8110-2020"},
    {"question": "压力管道元件型式试验依据。", "path": "TSG31-2025"},
    {"question": "压力管道元件许可审查依据。", "path": "TSG31-2025"},
    {"question": "超声检测报告依据。", "path": "47013.3-2023"},
    {"question": "射线检测底片质量依据。", "path": "47013.2-2015"},
    {"question": "磁粉检测验收依据。", "path": "47013.4-2015"},
    {"question": "渗透检测报告依据。", "path": "47013.5-2015"},
    {"question": "泄漏检测附录怎么查？", "path": "47013.8-2025"},
    {"question": "相控阵超声检测验收依据。", "path": "47013.15-2021"},
    {"question": "红外热成像检测依据。", "path": "47013.16-2024"},
    {"question": "管道监督检验范围依据。", "path": "TSG D7006-2020"},
    {"question": "阀门压力试验依据。", "path": "13927-2022"},
    {"question": "阀门检验和试验依据。", "path": "26480-2011"},
    {"question": "焊接材料订货技术条件依据。", "path": "47018-2017"},
    {"question": "焊接材料质量管理依据。", "path": "3223-2017"},
    {"question": "低中压锅炉管复验报告引用哪个标准？", "path": "3087-2022"},
    {"question": "低中压锅炉钢管质量证明书审查依据。", "path": "3087-2022"},
    {"question": "锅炉钢管复验报告应该引用什么标准？", "path": "3087-2022"},
    {"question": "高压锅炉钢管复验报告依据。", "path": "5310-2023"},
    {"question": "高压锅炉管质量证明书缺炉号引用哪个标准？", "path": "5310-2023"},
    {"question": "石化装置无缝钢管验收依据。", "path": "9948-2025"},
    {"question": "化工装置用无缝钢管质量证明书查什么？", "path": "9948-2025"},
    {"question": "不锈钢无缝管材料验收依据。", "path": "14976-2025"},
    {"question": "输送流体不锈钢无缝钢管质证书依据。", "path": "14976-2025"},
    {"question": "不锈钢焊管验收按哪个标准？", "path": "12771-2019"},
    {"question": "流体输送用不锈钢焊接钢管质保书依据。", "path": "12771-2019"},
    {"question": "普通流体无缝钢管质量证明书按哪个标准？", "path": "8163-2018"},
    {"question": "无缝钢管质保书没有炉号先查哪个标准？", "path": "8163-2018"},
    {"question": "焊材烘干记录引用哪个标准？", "path": "3223-2017"},
    {"question": "焊材保管温湿度管理依据。", "path": "3223-2017"},
    {"question": "焊条烘干保温记录依据。", "path": "3223-2017"},
    {"question": "焊材库管理按哪个规程？", "path": "3223-2017"},
    {"question": "承压设备用焊接材料订货验收依据。", "path": "47018-2017"},
    {"question": "焊材订货技术条件引用哪个标准？", "path": "47018-2017"},
    {"question": "焊接材料验收技术条件查哪个文件？", "path": "47018-2017"},
    {"question": "实心气保焊丝材质验收依据。", "path": "8110-2020"},
    {"question": "熔化极气体保护电弧焊焊丝型号依据。", "path": "8110-2020"},
    {"question": "非合金钢焊条型号验收依据。", "path": "5117-2012"},
    {"question": "细晶粒钢焊条验收查哪个标准？", "path": "5117-2012"},
    {"question": "焊接工艺评定报告引用什么标准？", "path": "47014-2023"},
    {"question": "承压设备焊评依据。", "path": "47014-2023"},
    {"question": "PQR 审核按哪个标准？", "path": "47014-2023"},
    {"question": "压力管道元件证书许可项目怎么查？", "path": "TSG31-2025"},
    {"question": "管道元件型式试验报告依据。", "path": "TSG31-2025"},
    {"question": "压力管道元件制造许可审查依据。", "path": "TSG31-2025"},
    {"question": "压力管道监督检验范围如何确定？", "path": "TSG D7006-2020"},
    {"question": "管道监检报告引用哪个规则？", "path": "TSG D7006-2020"},
    {"question": "监督检验规则里质量证明文件怎么查？", "path": "TSG D7006-2020"},
    {"question": "安全阀校验报告引用哪个规程？", "path": "92—2026"},
    {"question": "安全附件检验依据是什么？", "path": "92—2026"},
    {"question": "承压类特种设备安全附件验收依据。", "path": "92—2026"},
    {"question": "阀门壳体压力试验依据。", "path": "13927-2022"},
    {"question": "阀门密封试验报告按哪个标准？", "path": "13927-2022"},
    {"question": "工业阀门出厂检验引用哪个标准？", "path": "26480-2011"},
    {"question": "阀门检验试验记录依据。", "path": "26480-2011"},
    {"question": "普通超声检测验收等级依据。", "path": "47013.3-2023"},
    {"question": "普通超声检测报告审查依据。", "path": "47013.3-2023"},
    {"question": "相控阵检测报告按哪个标准？", "path": "47013.15-2021"},
    {"question": "PAUT 验收依据。", "path": "47013.15-2021"},
    {"question": "TOFD 检测报告依据。", "path": "47013.10-2015"},
    {"question": "衍射时差法超声检测验收标准。", "path": "47013.10-2015"},
    {"question": "射线底片黑度和像质计依据。", "path": "47013.2-2015"},
    {"question": "RT 检测报告依据。", "path": "47013.2-2015"},
    {"question": "DR 检测报告引用哪个标准？", "path": "47013.11-2023"},
    {"question": "X 射线数字成像检测报告依据。", "path": "47013.11-2023"},
    {"question": "CR 检测报告引用哪个标准？", "path": "47013.14-2023"},
    {"question": "射线计算机辅助成像验收依据。", "path": "47013.14-2023"},
    {"question": "磁粉检测报告依据。", "path": "47013.4-2015"},
    {"question": "MT 检测验收等级依据。", "path": "47013.4-2015"},
    {"question": "渗透检测报告引用哪个标准？", "path": "47013.5-2015"},
    {"question": "PT 检测验收等级依据。", "path": "47013.5-2015"},
    {"question": "涡流检测报告依据。", "path": "47013.6-2015"},
    {"question": "ET 检测验收依据。", "path": "47013.6-2015"},
    {"question": "目视检测报告依据。", "path": "47013.7-2012"},
    {"question": "VT 检测记录按哪个标准？", "path": "47013.7-2012"},
    {"question": "泄漏检测附录和正文依据。", "path": "47013.8-2025"},
    {"question": "密封性检测报告按哪个标准？", "path": "47013.8-2025"},
    {"question": "声发射检测报告依据。", "path": "47013.9-2012"},
    {"question": "AE 检测审查依据。", "path": "47013.9-2012"},
    {"question": "漏磁检测依据。", "path": "47013.12-2015"},
    {"question": "MFL 检测报告引用哪个标准？", "path": "47013.12-2015"},
    {"question": "脉冲涡流检测依据。", "path": "47013.13-2015"},
    {"question": "PECT 检测记录依据。", "path": "47013.13-2015"},
    {"question": "红外热成像报告依据。", "path": "47013.16-2024"},
    {"question": "红外检测审查按哪个标准？", "path": "47013.16-2024"},
    {"question": "磁记忆检测报告依据。", "path": "47013.17-2024"},
    {"question": "金属磁记忆检测引用哪个标准？", "path": "47013.17-2024"},
    {"question": "阵列涡流检测报告依据。", "path": "47013.18-2024"},
    {"question": "AECT 检测依据。", "path": "47013.18-2024"},
    {"question": "防腐层漏点检测电压怎么确定？", "path": "4113.11—2023"},
    {"question": "电火花检漏引用哪个方法标准？", "path": "4113.11—2023"},
    {"question": "管道防腐层性能试验漏点检测依据。", "path": "4113.11—2023"},
    {"question": "埋地钢质管道腐蚀防护工程检验依据。", "path": "19285-2026"},
    {"question": "腐蚀防护工程检验报告引用哪个标准？", "path": "19285-2026"},
    {"question": "埋地管道阴极保护检查引用什么标准？", "path": "21448-2017"},
    {"question": "阴极保护技术规范审查依据。", "path": "21448-2017"},
    {"question": "阴极保护技术条件审查依据。", "path": "33378-2025"},
    {"question": "工业管道施工规范引用哪个文件？", "path": "50235-2010"},
    {"question": "工业金属管道工程施工验收依据。", "path": "50184-2011"},
    {"question": "工业管道焊接施工规范依据。", "path": "50236-2011"},
    {"question": "管件类型与参数引用哪个标准？", "path": "12459-2025"},
    {"question": "钢制对焊管件技术规范依据。", "path": "13401-2025"},
    {"question": "油气输送管道跨越工程施工依据。", "path": "50460-2015"},
    {"question": "油气管道工程设计规范依据。", "path": "50424-2015"},
    {"question": "特种设备生产许可规则引用哪个文件？", "path": "TSG 07-2019"},
    {"question": "特种设备检验人员证考核依据。", "path": "特种设备检验人员考核规则"},
    {"question": "焊接人员考试规则依据。", "path": "TSGZ6002-2010"},
    {"question": "特种设备检验机构核准规则依据。", "path": "TSG Z7002"},
]


NON_SPATIAL_SOURCE_METHODS = {
    "deterministic_text_parse",
    "deterministic_docx_parse",
    "deterministic_yaml_parse",
    "deterministic_json_parse",
    "deterministic_csv_parse",
}


def ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def bbox_applicable(chunk: dict[str, Any]) -> bool:
    """Return whether the source has page geometry that must be grounded."""
    if chunk.get("contextType") == "business_rule_context":
        return False
    source_method = str(chunk.get("sourceMethod") or "").strip().lower()
    return source_method not in NON_SPATIAL_SOURCE_METHODS


def source_files() -> list[dict[str, Any]]:
    return [
        item
        for item in repo.state.get("knowledge_files", [])
        if item.get("sourceId") == STANDARD_RULES_SOURCE_ID
    ]


def path_hit(clauses: list[dict[str, Any]], expected: str, top_k: int) -> bool:
    expected_norm = expected.lower().replace("_", " ").replace("/", " ")
    for clause in clauses[:top_k]:
        path = str(clause.get("sourceRelativePath") or "").lower().replace("_", " ").replace("/", " ")
        title = str(clause.get("title") or "").lower().replace("_", " ").replace("/", " ")
        if expected_norm in path or expected_norm in title:
            return True
    return False


def clause_context_type(clause: dict[str, Any]) -> str:
    scope = clause.get("scope") if isinstance(clause.get("scope"), dict) else {}
    return str(clause.get("contextType") or scope.get("contextType") or "")


def evaluate_retrieval(top_k: int = 5) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in GOLDEN_CASES:
        retrieval = retrieve_knowledge_clauses(
            repo.state,
            query=case["question"],
            business_pack_id=DEFAULT_BUSINESS_PACK_ID,
            top_k=max(5, top_k),
            query_type="knowledge_quality_audit",
        )
        clauses = retrieval.get("clauses") or []
        top3 = path_hit(clauses, case["path"], 3)
        top5 = path_hit(clauses, case["path"], 5)
        top1 = clauses[0] if clauses else {}
        top1_path = str(top1.get("sourceRelativePath") or "")
        top1_context_type = clause_context_type(top1)
        results.append(
            {
                "question": case["question"],
                "expectedPathContains": case["path"],
                "top3": top3,
                "top5": top5,
                "top1SourceRelativePath": top1_path,
                "top1ContextType": top1_context_type,
                "businessRuleTop1OverStandardOriginal": top5 and top1_context_type == "business_rule_context",
                "selectedRoute": (retrieval.get("trace") or {}).get("selectedRoute"),
            }
        )
    top3_rate = ratio(sum(1 for item in results if item["top3"]), len(results))
    top5_rate = ratio(sum(1 for item in results if item["top5"]), len(results))
    wrong_rate = ratio(sum(1 for item in results if not item["top5"]), len(results))
    business_rule_top1_risks = [item for item in results if item["businessRuleTop1OverStandardOriginal"]]
    return {
        "caseCount": len(results),
        "top3Rate": top3_rate,
        "top5Rate": top5_rate,
        "wrongReferenceRate": wrong_rate,
        "businessRuleTop1RiskRate": ratio(len(business_rule_top1_risks), len(results)),
        "failedCases": [item for item in results if not item["top5"]],
        "businessRuleTop1Risks": business_rule_top1_risks,
        "caseResults": results,
    }


def build_audit() -> dict[str, Any]:
    files = source_files()
    file_ids = {str(item.get("id")) for item in files}
    chunks = [item for item in repo.state.get("knowledge_chunks", []) if str(item.get("fileId") or "") in file_ids]
    vectors = [item for item in repo.state.get("knowledge_vectors", []) if str(item.get("fileId") or "") in file_ids]
    chunks_by_file: dict[str, list[dict[str, Any]]] = {}
    vectors_by_file: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        chunks_by_file.setdefault(str(chunk.get("fileId")), []).append(chunk)
    for vector in vectors:
        vectors_by_file.setdefault(str(vector.get("fileId")), []).append(vector)

    vectorized_files = [item for item in files if item.get("vectorStatus") == "已向量化"]
    parity_files = [
        item
        for item in files
        if len(chunks_by_file.get(str(item.get("id")), [])) > 0
        and len(chunks_by_file.get(str(item.get("id")), [])) == len(vectors_by_file.get(str(item.get("id")), []))
    ]
    qwen_vectors = [
        item
        for item in vectors
        if item.get("embeddingModel") == QWEN3_EMBEDDING_MODEL
        and item.get("indexVersion") == QWEN3_INDEX_VERSION
        and int(item.get("dimensions") or 0) == 1024
    ]
    qwen_files = {str(item.get("fileId")) for item in qwen_vectors}
    original_chunks = [
        item
        for item in chunks
        if item.get("contextType") != "visual_extracted_reference"
        and item.get("sourceMethod") != "codex_visual_manual_extraction"
        and not item.get("needsHumanVerification")
        and not noise_like_text(item.get("text"))
    ]
    noise_chunks = [item for item in chunks if noise_like_text(item.get("text"))]
    bbox_eligible_chunks = [item for item in original_chunks if bbox_applicable(item)]
    bbox_not_applicable_chunks = [item for item in original_chunks if not bbox_applicable(item)]
    bbox_chunks = [item for item in bbox_eligible_chunks if item.get("bbox")]
    ocr_confidence_chunks = [item for item in original_chunks if item.get("ocrConfidence") is not None]
    business_chunks = [item for item in chunks if item.get("contextType") == "business_rule_context"]
    visual_chunks = [
        item
        for item in chunks
        if item.get("contextType") == "visual_extracted_reference"
        or item.get("sourceMethod") == "codex_visual_manual_extraction"
    ]
    retrieval = evaluate_retrieval()

    file_count = len(files)
    active_index_rate = ratio(len(qwen_files), file_count)
    file_coverage_rate = ratio(len(vectorized_files), file_count)
    parity_rate = ratio(len(parity_files), file_count)
    original_text_rate = ratio(len(original_chunks), len(chunks))
    noise_chunk_rate = ratio(len(noise_chunks), len(chunks))
    bbox_rate = ratio(len(bbox_chunks), len(bbox_eligible_chunks)) if bbox_eligible_chunks else 1.0
    ocr_confidence_rate = ratio(len(ocr_confidence_chunks), len(original_chunks))

    score = 0.0
    score += min(file_coverage_rate, 1.0) * 15
    score += min(parity_rate, 1.0) * 15
    score += min(active_index_rate, 1.0) * 20
    score += min(original_text_rate / 0.92, 1.0) * 15
    score += min(bbox_rate / 0.90, 1.0) * 10
    score += min(ocr_confidence_rate / 0.90, 1.0) * 5
    retrieval_component = (
        min(retrieval["top3Rate"] / 0.98, 1.0) * 0.7
        + min(retrieval["top5Rate"] / 0.99, 1.0) * 0.3
    )
    score += retrieval_component * 20
    score -= max(0.0, retrieval["wrongReferenceRate"] - 0.01) * 100
    score -= retrieval["businessRuleTop1RiskRate"] * 50
    score -= min(15.0, noise_chunk_rate * 100.0)
    score = round(max(0.0, min(100.0, score)), 1)

    gates = {
        "fileCoverage": file_coverage_rate >= 1.0,
        "vectorParity": parity_rate >= 1.0,
        "activeQwenIndex": active_index_rate >= 1.0,
        "originalTextRate": original_text_rate >= 0.92,
        "bboxRate": bbox_rate >= 0.90,
        "noiseChunkRate": noise_chunk_rate <= 0.01,
        "retrievalTop3": retrieval["top3Rate"] >= 0.98,
        "retrievalTop5": retrieval["top5Rate"] >= 0.99,
        "wrongReferenceRate": retrieval["wrongReferenceRate"] <= 0.01,
        "businessRuleTop1Risk": retrieval["businessRuleTop1RiskRate"] <= 0,
    }
    return {
        "schemaVersion": "aicheck-knowledge-quality-audit-v1",
        "score": score,
        "targetScore": 97,
        "ok": score >= 97 and all(gates.values()),
        "sourceId": STANDARD_RULES_SOURCE_ID,
        "activeEmbeddingModel": QWEN3_EMBEDDING_MODEL,
        "activeIndexVersion": QWEN3_INDEX_VERSION,
        "metrics": {
            "fileCount": file_count,
            "vectorizedFiles": len(vectorized_files),
            "chunkCount": len(chunks),
            "vectorCount": len(vectors),
            "qwenVectorCount": len(qwen_vectors),
            "fileCoverageRate": file_coverage_rate,
            "vectorParityRate": parity_rate,
            "activeQwenIndexRate": active_index_rate,
            "originalTextChunkRate": original_text_rate,
            "noiseLikeWatermarkChunks": len(noise_chunks),
            "noiseLikeWatermarkRate": noise_chunk_rate,
            "bboxRate": bbox_rate,
            "bboxEligibleChunks": len(bbox_eligible_chunks),
            "bboxCoveredChunks": len(bbox_chunks),
            "bboxNotApplicableChunks": len(bbox_not_applicable_chunks),
            "ocrConfidenceRate": ocr_confidence_rate,
            "businessRuleContextChunks": len(business_chunks),
            "visualSummaryChunks": len(visual_chunks),
        },
        "retrieval": retrieval,
        "gates": gates,
        "blockers": [name for name, passed in gates.items() if not passed],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only quality audit for rules knowledge vectors.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON.")
    parser.add_argument("--fail-under", type=float, default=90.0, help="Exit non-zero when score is below this value.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo.configure_sync_postgres()
    load_state()
    audit = build_audit()
    print(json.dumps(audit, ensure_ascii=False, indent=None if args.json else 2, separators=(",", ":") if args.json else None))
    if float(args.fail_under) <= 0:
        return 0
    return 0 if float(audit["score"]) >= float(args.fail_under) and audit["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
