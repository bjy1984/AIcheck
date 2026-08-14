"""把检索到的条款整理成能送进提示词的形态（issue #12 D-3）。

D-3 记的是「主链路检索是固定模板词的词法检索」。实测发现问题不在查询词，
而在**检索结果压根没送出去**：

- retrieve_knowledge 跑完把条款存进 context["knowledgeClauses"]，然后无人读取；
- 提示词里只有 retrievalTraceIds 一串 ID；
- 而输出 schema 要求模型产出 kbRefs: [{retrievalTraceId, clauseIds}]。

模型手里没有任何 clauseId，这个要求根本无法满足——线上 3 条 finding 的 kbRefs
全是空的。实测把 knowledgeClauses 清空，整个提示词只有 traceId 那一处变化，
等于这一步白跑。

改查询词不会改变任何东西：送不出去的东西，查得再准也没用。
"""

from __future__ import annotations

from typing import Any

# 单次送进提示词的条款数上限。检索 top_k 是 5，这里留一点余量。
MAX_RETRIEVED_CLAUSES = 8

# 单条条款正文的截断长度。条款动辄上千字，全量送会把刚省下来的预算重新吃掉
# ——工具目录裁剪那轮刚把固定开销从 41% 压到 7.7%。
MAX_CLAUSE_TEXT_CHARS = 400


def retrieved_clause_digest(clauses: Any) -> list[dict[str, Any]]:
    """送给模型的条款摘要：ID + 正文 + 出处。

    只给 ID 模型无法判断相关性，只给正文模型无法引用——两个都要。
    截断要标出来：不标的话模型会把半句话当成完整条款去判定。
    """
    digest: list[dict[str, Any]] = []
    for item in clauses or []:
        if not isinstance(item, dict):
            continue
        clause_id = str(item.get("clauseId") or "")
        text = str(item.get("text") or "").strip()
        if not clause_id or not text:
            continue
        digest.append(
            {
                "clauseId": clause_id,
                "text": text[:MAX_CLAUSE_TEXT_CHARS],
                "truncated": len(text) > MAX_CLAUSE_TEXT_CHARS,
                "source": str(item.get("sourceTitle") or item.get("standardCode") or ""),
            }
        )
    return digest[:MAX_RETRIEVED_CLAUSES]
