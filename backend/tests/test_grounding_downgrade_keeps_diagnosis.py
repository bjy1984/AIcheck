"""降级要降结论的效力，不是把诊断信息一起抹掉。

## 线上实测（2026-08-14，节点 2，RRUN-DD7097107E）

正式 ReviewRun 首次完整跑通，模型花 5,245 token（含推理 3,619）产出三条具体诊断，
例如「仅识别到证书编号、单位名称、有效期至等字段，未提取到『许可范围/级别/类别』」。

而监检在界面上看到的是三条**一模一样**的：

    「当前 OCR 证据不足以支撑模型输出的业务结论，已降级为待人工确认；
      请核对原件、OCR 文本、表格、印章和证据链。」

降级本身是对的——缺 2 项必传资料，确实不能判「符合」。错在连诊断一起覆盖：
真正该去查的那份扫描件、那个字段，全没了，监检得从头再查一遍。

## 两类降级原因，处置必须不同

    证据不足（缺字段、缺资料）  模型诊断的是缺口本身 → 保留，它指出去查什么
    unsupportedClaims          模型断言了没有依据的事 → 丢弃

第二类的危险是具体的：既有用例里模型写「焊工王建国证书编号、有效期和持证项目与
焊接工艺要求匹配，建议通过」——一个凭空产生的结论。加再多警告横幅也不该把它摆到
监检面前，人会记住那个名字。这两条用例（test_contract / test_fde_console）
在我第一版实现里变红，拦住了一次真实的安全回退。

## 正面断言检测器的误报：修了一类，留了一类

线上三条里有一条被判 UNSUPPORTED_LLM_CLAIM，理由包括
`{"claim": "DV-SCAN66B96692-V1", "reason": "not_present_in_supplied_evidence"}`
——那是**我们自己发给模型的文档版本号**。模型复述它按定义不可能是幻觉，
而检测器只拿 OCR 正文比对，看不见这些标识符。这一类已修（见文件末尾用例）。

**未修的那一类**：POSITIVE_CLAIM_RE 只做关键词匹配、不处理否定，
「规则要求核查许可范围是否覆盖」这种陈述要查什么的句子也会命中「覆盖」。
放松它的代价是真实幻觉漏出去，所以从严保留——代价是这类 finding 的诊断
仍会被丢掉，监检看到的是模板。这是当前 AI 复核可用性的主要瓶颈。
"""

from __future__ import annotations

from libs.review_grounding import apply_grounding_guardrails

# —— 第一类：模型诊断的是缺口（线上三条里有两条属于此类，unsupportedClaims 为空）
GAP_TITLE = "许可证扫描件未解析出「许可范围」行"
GAP_DESCRIPTION = (
    "资料 DV-SCAN66B96692-V1 第 1 页的表格解析返回 0 行，"
    "未能取到「许可范围」「级别」「类别」三个字段，需人工打开原件核对该表。"
)

# —— 第二类：模型断言了没有依据的事（既有用例 test_contract 的真实文本）
CLAIM_TITLE = "资料复核建议"
CLAIM_DESCRIPTION = "焊工王建国证书编号、有效期和持证项目与焊接工艺要求匹配，建议通过。"


def _draft(title: str, description: str) -> dict:
    return {
        "title": title,
        "description": description,
        "confidence": 0.9,
        "evidenceRefs": [
            {
                "evidenceLinkId": "EV-DV-SCAN66B96692-V1-1",
                "documentVersionId": "DV-SCAN66B96692-V1",
                "pageNo": 1,
            }
        ],
    }


def _insufficient_input() -> dict:
    return {
        "groundingStatus": "insufficient_evidence",
        "evidenceLinks": [
            {"id": "EV-DV-SCAN66B96692-V1-1", "documentVersionId": "DV-SCAN66B96692-V1", "pageNo": 1}
        ],
        "evidenceTextCorpus": ["证书编号 TS3234", "有效期至 2028 年"],
    }


def _guard(title: str, description: str) -> dict:
    return apply_grounding_guardrails([_draft(title, description)], _insufficient_input())[0]


# ── 第一类：诊断要保住 ────────────────────────────────────────────────


def test_诊断信息不能被模板覆盖():
    """监检要知道的是「去查哪一份、查哪个字段」，不是「请核对原件」。"""
    guarded = _guard(GAP_TITLE, GAP_DESCRIPTION)
    assert not guarded["unsupportedClaims"], "这条不该被判成无据断言，测试前提就不成立"
    assert "许可范围" in guarded["description"], "模型指出的具体缺失字段被抹掉了"
    assert "DV-SCAN66B96692-V1" in guarded["description"], "该去查哪份资料的线索没了"


def test_降级说明必须排在最前():
    """任何照直渲染 description 的地方，第一眼读到的必须是「未经核实」。

    反过来（原文在前、说明在后）会让人把 AI 初判当成已核实的结论——
    这条链路出的是监督检验意见，读错一次的代价不是重跑一遍。
    """
    text = _guard(GAP_TITLE, GAP_DESCRIPTION)["description"]
    assert text.lstrip().startswith("⚠️")
    assert "未经证据核实" in text
    assert text.index("未经证据核实") < text.index("许可范围")
    assert "不得直接作为监督检验结论" in text


def test_模型原文另存一份供界面单独呈现():
    guarded = _guard(GAP_TITLE, GAP_DESCRIPTION)
    assert guarded["modelTitle"] == GAP_TITLE
    assert guarded["modelDescription"] == GAP_DESCRIPTION


def test_模型没写内容时不留悬空标题():
    guarded = _guard("", "")
    assert "⚠️" not in guarded["description"]
    assert "请核对原件" in guarded["description"]


# ── 第二类：无据断言要丢干净 ──────────────────────────────────────────


def test_无据断言的原文一个字都不能带出来():
    """「焊工王建国…建议通过」是凭空产生的结论。

    加警告横幅也不行——人会记住那个名字。这条在第一版实现里是红的。
    """
    guarded = _guard(CLAIM_TITLE, CLAIM_DESCRIPTION)
    assert guarded["unsupportedClaims"], "测试前提：这条应被判为无据断言"
    assert "王建国" not in guarded["description"]
    assert "建议通过" not in guarded["description"]
    # 也不能从侧门漏出去
    assert "王建国" not in str(guarded.get("modelDescription") or "")
    assert "王建国" not in str(guarded.get("modelTitle") or "")


def test_无据断言仍要告诉人去哪看原因():
    """丢掉原文不等于什么都不说——unsupportedClaims 里有具体是哪几句没依据。"""
    text = _guard(CLAIM_TITLE, CLAIM_DESCRIPTION)["description"]
    assert "unsupportedClaims" in text
    assert "已整条丢弃" in text


# ── 两类都要降级 ─────────────────────────────────────────────────────


def test_结论效力照旧被降级():
    """保留诊断不等于放行结论。降级该降的一样不能少。"""
    for title, description in ((GAP_TITLE, GAP_DESCRIPTION), (CLAIM_TITLE, CLAIM_DESCRIPTION)):
        guarded = _guard(title, description)
        assert guarded["title"] == "证据不足，需人工确认"
        assert guarded["groundingStatus"] == "insufficient_evidence"
        assert guarded["suggestedAction"] == "human_confirm"
        assert guarded["confidence"] <= 0.5


def test_证据充分时不动模型原文():
    """降级逻辑只在证据不足时介入，正常路径一个字都不该改。"""
    grounded = {
        "groundingStatus": "grounded",
        "evidenceLinks": [
            {"id": "EV-DV-SCAN66B96692-V1-1", "documentVersionId": "DV-SCAN66B96692-V1", "pageNo": 1}
        ],
        "evidenceTextCorpus": [GAP_DESCRIPTION],
    }
    guarded = apply_grounding_guardrails(
        [_draft("许可范围行已解析", "第 1 页表格取到 3 行")], grounded
    )[0]
    assert guarded["title"] == "许可范围行已解析"
    assert "⚠️" not in guarded["description"]


# ── 引用我们自己给的 ID 不算无据断言 ──────────────────────────────────


def test_模型复述我们给的资料编号不算幻觉():
    """线上 RRUN-DD7097107E 的真实误判：

        {"claim": "DV-SCAN66B96692-V1", "reason": "not_present_in_supplied_evidence"}

    那是我们发给模型的文档版本号。模型复述它按定义不可能是幻觉，
    而检测器只拿 OCR 正文比对，看不见这些标识符——整条诊断因此被丢掉。
    """
    guarded = _guard(GAP_TITLE, GAP_DESCRIPTION)
    flagged = {str(c.get("claim")) for c in guarded.get("unsupportedClaims") or []}
    assert "DV-SCAN66B96692-V1" not in flagged


def test_规则正文里的等级词仍从严():
    """规则里写着 GC1/GC2/GCD，模型说「覆盖 GC2」时究竟是在复述要求
    还是在下结论，无法从字面区分——那一类不放行。"""
    from libs.review_grounding import unsupported_claims

    corpus = ["证书编号 TS3234", "有效期至 2028 年"]
    claims = unsupported_claims("施工单位许可范围覆盖 GC2 级管道", corpus)
    assert claims, "无据的等级覆盖断言必须被拦住"


def test_没有标识符时行为不变():
    from libs.review_grounding import _supplied_identifiers

    assert _supplied_identifiers({}) == []
    assert _supplied_identifiers({"evidenceLinks": [None, 3]}) == []
