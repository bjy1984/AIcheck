"""第一阶段止血（2026-11-02 server8 复盘）：AI 发现 113 条里 74 条被整条丢弃只剩模板句、
16 条是噪音、7 条「有据」里 4 条是错的缺项断言。四处修法各钉一条。"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from libs.business_pack import load_business_pack
from libs.review_grounding import (
    _claim_tokens,
    apply_grounding_guardrails,
    grounding_input_with_supplements,
)
from libs.review_orchestrator import execution as ex
from libs.review_orchestrator.output_contract import SHARD_SCOPE_REQUIREMENT
from libs.review_orchestrator.shard_execution import aggregate_shard_findings, evidence_shard_scope

TEMPLATE = "证据不足，需人工确认"


def _grounding_input(text: str = "设计说明 4.3 无损检测按 NB/T 47013-2015") -> dict:
    link = {"id": "EVL-1", "documentVersionId": "DV-1", "pageNo": 1, "bbox": [1, 1, 9, 9], "quotedText": text}
    return {
        "groundingStatus": "grounded",
        "documentVersionIds": ["DV-1"],
        "evidenceTextCorpus": [text],
        "fragments": [{"id": "FRAG-1", "documentVersionId": "DV-1", "text": text, "pageNo": 1, "bbox": [1, 1, 9, 9]}],
        "fields": [], "tables": [], "seals": [],
        "evidenceLinks": [link],
        "reviewMode": "gap_precheck",
    }


def _ref(quote: str = "") -> dict:
    return {"evidenceLinkId": "EVL-1", "documentVersionId": "DV-1", "pageNo": 1, "bbox": [1, 1, 9, 9], "quotedText": quote}


# ── 一、标准号不再被切成「日期」碎片 ──────────────────────────────────────────

def test_four_digit_runs_inside_standard_numbers_are_not_date_claims() -> None:
    tokens = set(_claim_tokens("GB/T 12459-2017、GB 50316-2000 已废止"))
    assert "1245" not in tokens and "5031" not in tokens and "2459" not in tokens
    assert {"2017", "2000"} <= tokens
    assert "2028年1月17日" in set(_claim_tokens("有效期至2028年1月17日"))


# ── 二、复述工具结果里的标准号与日期不算无据 ─────────────────────────────────

def test_restating_a_tool_found_withdrawal_date_is_not_discarded() -> None:
    draft = {
        "id": "F-1", "severity": "medium", "suggestedAction": "human_confirm",
        "title": "管件标准已废止，现行有效的是新版",
        "description": "设计引用的 GB/T 12459-2017 已于 2026-05-01 废止，现行有效的是新版。",
        "evidenceRefs": [_ref("管件 GB/T 12459-2017")],
    }
    grounding = _grounding_input("管件 GB/T 12459-2017")
    context = {"groundingInput": grounding, "ruleResults": [{"ruleId": "R08", "toolOutputs": [
        {"standardCode": "GB/T 12459-2017", "status": "abolished", "abolishedOn": "2026-05-01"}]}]}
    without_tools = apply_grounding_guardrails([deepcopy(draft)], grounding)[0]
    with_tools = apply_grounding_guardrails([deepcopy(draft)], grounding_input_with_supplements(context))[0]
    assert any(c["claim"].startswith("2026-05-01") for c in without_tools["unsupportedClaims"])
    assert with_tools["unsupportedClaims"] == []
    assert with_tools["title"] == draft["title"]


# ── 三、缺项断言没有引文不能算有据，但原文保留 ───────────────────────────────

def test_a_missing_item_claim_without_quote_is_downgraded_but_keeps_its_text() -> None:
    draft = {
        "id": "F-2", "severity": "medium", "suggestedAction": "human_confirm",
        "title": "无损检测设计要求缺检测比例与合格级别",
        "description": "查到设计说明提及射线检测要求，但未明确检测比例和合格级别。",
        "evidenceRefs": [_ref("")],
    }
    guarded = apply_grounding_guardrails([draft], _grounding_input())[0]
    assert guarded["groundingStatus"] == "insufficient_evidence"
    assert guarded["modelTitle"] == draft["title"]
    assert "未明确检测比例" in guarded["description"]
    assert any(item["code"] == "ABSENCE_CLAIM_WITHOUT_QUOTE" for item in guarded["evidenceValidationFailures"])


def test_a_quoted_gap_and_a_defect_word_are_not_treated_as_unquoted_absence() -> None:
    quoted = {
        "id": "F-3", "severity": "medium", "suggestedAction": "human_confirm",
        "title": "泄漏试验未规定试验压力",
        "description": "特性表泄漏试验栏只打了勾，没有写试验压力。",
        "evidenceRefs": [_ref("设计说明 4.3 无损检测按 NB/T 47013-2015")],
    }
    defect = {**quoted, "id": "F-4", "title": "射线底片显示缺陷位置", "description": "底片上的缺陷位于焊缝根部。"}
    for draft in (quoted, defect):
        failures = apply_grounding_guardrails([draft], _grounding_input())[0].get("evidenceValidationFailures") or []
        assert not any(item["code"] == "ABSENCE_CLAIM_WITHOUT_QUOTE" for item in failures), draft["title"]


# ── 四、提示词告诉模型分片范围；要求各片相同，范围本身排最后 ─────────────────

def test_shard_scope_names_the_documents_and_the_prompt_forbids_cross_shard_absence(monkeypatch) -> None:
    state = {
        "versions": [{"id": "DV-1", "documentId": "DOC-1"}, {"id": "DV-2", "documentId": "DOC-2"}],
        "documents": [{"id": "DOC-1", "fileName": "设计说明.png"}, {"id": "DOC-2", "fileName": "管道特性表.png"}],
    }
    shard = {"shardIndex": 1, "artifactSegments": [{"documentVersionId": "DV-1"}, {"documentVersionId": "DV-1"}]}
    scope = evidence_shard_scope(state, shard, 8)
    assert scope == {"shardIndex": 1, "shardCount": 8,
                     "documents": [{"documentVersionId": "DV-1", "fileName": "设计说明.png"}]}

    monkeypatch.setattr(ex, "repo", SimpleNamespace(state={"ocr_parse_results": []}, clone=deepcopy))
    monkeypatch.setattr(ex, "select_prompt_template", lambda _: None)
    monkeypatch.setattr(ex, "station_snapshot", lambda _run: {"systemPrompt": "你是监检工位。"})
    monkeypatch.setattr(ex, "scope_catalog", lambda _run, _catalog: ([], {}))
    monkeypatch.setattr(ex, "audit_runtime_public_config", lambda **kwargs: {})
    monkeypatch.setattr(ex.checklist_mode, "checklist_enabled", lambda: False)
    context = {"project": {"businessPackSnapshot": load_business_pack("engineering_inspection_v1")},
               "auditRuntime": {"mode": "structured"}, "ruleResults": [],
               "groundingInput": _grounding_input(), "evidenceShardScope": scope}
    payload = ex.build_review_prompt_parts({"projectId": "P", "nodeId": 9}, context)["userPayload"]
    assert SHARD_SCOPE_REQUIREMENT in payload["requirements"]
    assert list(payload)[-1] == "evidenceShardScope" and payload["evidenceShardScope"] == scope

    context.pop("evidenceShardScope")
    unsharded = ex.build_review_prompt_parts({"projectId": "P", "nodeId": 9}, context)["userPayload"]
    assert SHARD_SCOPE_REQUIREMENT not in unsharded["requirements"] and "evidenceShardScope" not in unsharded


# ── 五、同义合并、元信息不单列、模板句一节点一条 ─────────────────────────────

def _kept(fid: str, title: str, body: str, *, grounded: bool = False) -> dict:
    finding = {"id": fid, "findingType": "design_review", "severity": "medium", "suggestedAction": "human_confirm",
               "evidenceRefs": [], "ruleRefs": [], "kbRefs": []}
    if grounded:
        return {**finding, "title": title, "description": body, "groundingStatus": "grounded"}
    return {**finding, "title": TEMPLATE, "modelTitle": title, "modelDescription": body,
            "description": f"⚠️ 未经证据核实\n\n{title}\n{body}", "groundingStatus": "insufficient_evidence"}


def test_rewordings_merge_but_different_tests_and_meta_findings_do_not_survive_as_noise() -> None:
    drafts = [
        _kept("A", "缺失管道数据表及强度计算书等必备文件", "查到已上传设计说明及图纸目录；差在未见管道数据表、管道布置图、管道材料一览表及直管强度计算书。"),
        _kept("B", "缺失管道数据表等四项设计文件", "查到已上传设计说明及图纸目录等；差在缺少管道数据表、管道布置图、管道材料一览表及直管强度计算书。"),
        _kept("C", "缺失管道数据表及布置图等必备设计文件", "查到已上传设计说明及图纸目录，差在未见管道数据表、管道布置图、管道材料一览表及直管强度计算书。", grounded=True),
        _kept("D", "耐压试验设计要求缺试验压力与合格标准", "查到设计说明提及管道系统需进行耐压试验，但未明确试验压力值。"),
        _kept("E", "泄漏试验设计要求缺试验压力与合格标准", "查到设计说明提及管道系统需进行泄漏性试验，但未明确试验压力。"),
        _kept("F", "图纸关键结构化字段提取置信度低", "字段提取置信度为0，需人工核对原图字段。"),
        {"id": "G", "title": TEMPLATE, "description": "模板", "severity": "low", "unsupportedClaims": [{"claim": "2026-05-01"}],
         "evidenceRefs": [], "ruleRefs": [], "kbRefs": []},
        {"id": "H", "title": TEMPLATE, "description": "模板", "severity": "medium", "unsupportedClaims": [{"claim": "TS1844171"}],
         "evidenceRefs": [], "ruleRefs": [], "kbRefs": []},
    ]
    aggregate = aggregate_shard_findings({"reviewRunId": "R"}, [
        {"evidenceShardId": f"S{index}", "modelAttemptIds": [], "findingDrafts": [draft]} for index, draft in enumerate(drafts)])
    by_id = {row["id"]: row for row in aggregate["findingDrafts"]}

    # 三种写法的「缺设计文件」并成一条，有据的那条做底，被并的标题留着可查
    assert "C" in by_id and "A" not in by_id and "B" not in by_id
    assert set(by_id["C"]["mergedFindingIds"]) == {"A", "B"}
    assert set(by_id["C"]["mergedTitles"]) == {"缺失管道数据表及强度计算书等必备文件", "缺失管道数据表等四项设计文件"}
    # 耐压和泄漏句式几乎一样，但不是同一件事
    assert "D" in by_id and "E" in by_id
    # 读取质量类不单列，只留计数
    assert "F" not in by_id and aggregate["suppressedMetaFindings"]["count"] == 1
    # 只剩模板句的两条并成一条
    templates = [row for row in aggregate["findingDrafts"] if row["title"] == TEMPLATE and not row.get("modelTitle")]
    assert len(templates) == 1 and {c["claim"] for c in templates[0]["unsupportedClaims"]} == {"2026-05-01", "TS1844171"}
    assert templates[0]["severity"] == "medium"


# ── 六、重跑后发现的合并漏网：正文顺带提到别的事、繁体输出、印章 ───────────────

def test_same_issue_merges_despite_incidental_body_words_traditional_script_and_seals() -> None:
    drafts = [
        _kept("A", "无损检测要求缺比例与合格级别", "设计说明只写了按 NB/T 47013 射线检测，特性表未见检测比例。"),
        _kept("B", "无损检测要求缺比例与合格级别", "设计说明只写了射线检测按现行标准执行，未写比例与合格级别。"),
        _kept("C", "無損檢測比例與合格級別證據不足", "本片資料未見檢測比例。"),
        _kept("D", "制造许可证扫描件未识别出发证机关印章", "扫描件上看不到发证机关章。"),
        _kept("E", "生产许可证发证机关印章未识别需确认", "未见发证机关印章。"),
        _kept("F", "泄漏试验要求缺试验压力与合格标准", "设计说明提及泄漏试验，未写压力。"),
    ]
    aggregate = aggregate_shard_findings({"reviewRunId": "R"}, [
        {"evidenceShardId": f"S{index}", "modelAttemptIds": [], "findingDrafts": [draft]} for index, draft in enumerate(drafts)])
    by_id = {row["id"]: row for row in aggregate["findingDrafts"]}
    assert set(by_id) == {"A", "D", "F"}
    assert set(by_id["A"]["mergedFindingIds"]) == {"B", "C"}
    assert by_id["D"]["mergedFindingIds"] == ["E"]
