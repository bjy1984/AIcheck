"""检索到的条款要真的送给模型（issue #12 D-3）。

D-3 记的是「主链路检索是固定模板词的词法检索，pgvector 语义检索只在
retrieval-test 端点用」。实测发现问题不在查询词，而在**检索结果压根没送出去**：

- retrieve_knowledge 跑完把条款存进 context["knowledgeClauses"]，然后无人读取；
- 提示词里只有 retrievalTraceIds 一串 ID；
- 而输出 schema 要求模型产出 kbRefs: [{retrievalTraceId, clauseIds}]。

模型手里没有任何 clauseId，这个要求根本无法满足——线上 3 条 finding 的 kbRefs
全是空的。改查询词不会改变任何东西：送不出去的东西，查得再准也没用。
"""

from __future__ import annotations

from libs.review_orchestrator.clause_digest import (
    MAX_RETRIEVED_CLAUSES,
    retrieved_clause_digest,
)


def test_clause_id_and_text_are_both_sent() -> None:
    """只给 ID 模型判断不了相关性，只给正文模型无法引用——两个都要。"""
    digest = retrieved_clause_digest(
        [{"clauseId": "TSG-Z6002-3.2", "text": "焊工应持有有效的特种设备作业人员证。", "sourceTitle": "TSG Z6002"}]
    )
    assert digest[0]["clauseId"] == "TSG-Z6002-3.2"
    assert "焊工应持有" in digest[0]["text"]
    assert digest[0]["source"] == "TSG Z6002"


def test_long_clause_text_is_truncated_and_says_so() -> None:
    """条款动辄上千字，全量送会把刚省下来的预算重新吃掉。

    但截断必须标出来——不标的话模型会把半句话当成完整条款去判定。
    """
    digest = retrieved_clause_digest([{"clauseId": "C-1", "text": "条" * 900}])
    assert len(digest[0]["text"]) == 400
    assert digest[0]["truncated"] is True


def test_short_clause_is_not_marked_truncated() -> None:
    digest = retrieved_clause_digest([{"clauseId": "C-1", "text": "短条款"}])
    assert digest[0]["truncated"] is False


def test_clauses_without_id_or_text_are_dropped() -> None:
    """没有 ID 的条款送过去也没法被引用，没有正文的送过去等于噪音。"""
    digest = retrieved_clause_digest(
        [
            {"clauseId": "", "text": "有正文没 ID"},
            {"clauseId": "C-2", "text": "   "},
            {"clauseId": "C-3", "text": "两样都有"},
        ]
    )
    assert [item["clauseId"] for item in digest] == ["C-3"]


def test_digest_is_capped() -> None:
    """检索 top_k 是 5，这里留了余量；但不能不设上限——预算是有限的。"""
    many = [{"clauseId": f"C-{i}", "text": f"条款{i}"} for i in range(50)]
    assert len(retrieved_clause_digest(many)) == MAX_RETRIEVED_CLAUSES


def test_malformed_input_does_not_crash_the_prompt() -> None:
    """检索侧给了怪东西时不能把整次审查带崩——提示词构造在主链路上。"""
    assert retrieved_clause_digest(None) == []
    assert retrieved_clause_digest([None, 3, "x"]) == []
