"""发现引用的标准条款要能显示出来，而不是一串 clauseId。

2026-09-13 用户要求「引用的标准条款要清晰标记出来」。模型早就在引条款了
（kbRefs.clauseIds 从检索包里选 id，不是自己背原文——背原文就是幻觉入口），
但界面上只有 `CHK-KF-KB-DE16B8E7E8-14` 这种 id，等于没引。
"""
from __future__ import annotations

from libs.review_orchestrator.output_contract import attach_clause_details

STD_DOC = {"knowledgeFileId": "FILE-STD", "code": "TSG Z6002—2010", "name": "特种设备焊接操作人员考核细则"}

CLAUSE = {
    "id": "KC-CHK-1",
    "clauseId": "CHK-1",
    "clauseNo": "p12-c13",
    "title": "特种设备焊接操作人员考核细则 / 第三章 考核程序与要求",
    "text": "考试机构应当对焊工申请考试资料的完整性和相关记录表的真实性负责",
    "pageNo": 12,
    "documentVersionId": "DV-STD",
    "fileId": "FILE-STD",
}


def test_条款id被解析成标准名章节与原文():
    drafts = [{"title": "焊工证项目代号无法解码", "kbRefs": [{"clauseIds": ["CHK-1"], "retrievalTraceId": "RTR-1"}]}]
    attach_clause_details({"knowledge_clauses": [CLAUSE], "standard_document_versions": [STD_DOC]}, drafts)
    ref = drafts[0]["clauseRefs"][0]
    assert ref["standard"] == "特种设备焊接操作人员考核细则"
    assert ref["standardCode"] == "TSG Z6002—2010"
    # 2026-08-01 起 TSG Z6002-2026 施行：引 2010 版要当场标出来，否则监检照着过期规范核。
    assert ref["supersededEdition"]["supersededBy"] == "TSG Z6002-2026"
    assert ref["section"] == "第三章 考核程序与要求"
    assert ref["clauseNo"] == "p12-c13" and ref["pageNo"] == 12
    assert ref["text"].startswith("考试机构应当")


def test_同一条款只列一次_查不到的不编():
    drafts = [{"kbRefs": [{"clauseIds": ["CHK-1", "CHK-1", "CHK-UNKNOWN"]}]}]
    attach_clause_details({"knowledge_clauses": [CLAUSE], "standard_document_versions": [STD_DOC]}, drafts)
    assert [item["clauseId"] for item in drafts[0]["clauseRefs"]] == ["CHK-1"]


def test_没有kbRefs时不加字段():
    drafts = [{"title": "x"}]
    attach_clause_details({"knowledge_clauses": [CLAUSE]}, drafts)
    assert "clauseRefs" not in drafts[0]


def test_现行版本不提示换版():
    """新版施行前引旧版是对的，别乱标红。"""
    from libs.standard_editions import superseded_edition

    assert superseded_edition("TSG Z6002—2010", on="2026-07-31") is None
    assert superseded_edition("TSG Z6002—2010", on="2026-08-01")["supersededBy"] == "TSG Z6002-2026"
    assert superseded_edition("NB/T 47014-2023") is None, "本身就是现行版，不该标"
    assert superseded_edition("GB 50235—2010") is None, "没核实过的不登记，也就不提示"


PROJECT_FILE_CLAUSE = {
    "clauseId": "CHK-DOC",
    "clauseNo": "p3-c1",
    "title": "地上甲类储罐区2（含泵区）施工图.pdf / 管道布置",
    "text": "本工程管道按 GC2 级设计",
    "pageNo": 3,
    "fileId": "FILE-PROJECT",
}

UNREGISTERED_CLAUSE = {
    "clauseId": "CHK-UNREG",
    "clauseNo": "p5-c2",
    "title": "特种设备无损检测人员考核规则 / 第二章",
    "text": "无损检测人员应当按照本规则考核合格",
    "pageNo": 5,
    "fileId": "FILE-UNREG",
}


def test_工程资料原文不冒充标准条款():
    """2026-09-13 线上审计：P-2026-ECD202 的 296 条引用里 127 条没有标准号。

    引得最多的是「地上甲类储罐区2（含泵区）施工图.pdf」（40 次）——那是本工程的资料，
    不是规范要求。界面上一栏叫「引用的标准条款」，把它印进去等于告诉监检
    「规范这么规定的」。分三档标出来：标准条款 / 资料原文 / 标准但版本没登记。
    """
    drafts = [{"kbRefs": [{"clauseIds": ["CHK-1", "CHK-DOC", "CHK-UNREG"]}]}]
    attach_clause_details(
        {
            "knowledge_clauses": [CLAUSE, PROJECT_FILE_CLAUSE, UNREGISTERED_CLAUSE],
            "standard_document_versions": [STD_DOC],
        },
        drafts,
    )
    kinds = {ref["clauseId"]: ref["sourceKind"] for ref in drafts[0]["clauseRefs"]}
    assert kinds == {"CHK-1": "standard", "CHK-DOC": "document", "CHK-UNREG": "unregistered_standard"}
