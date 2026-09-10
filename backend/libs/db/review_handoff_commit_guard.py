"""提交结论时，在写入的同一个事务里复核交接来源。

执行前那道闸（`review_live_sources.ensure_live_document_sources`）用的是另一条连接的
只读事务，落库又是后面另一次事务。两者之间有窗口：闸放行之后、结果写下去之前，
上游交接可能被别的程序改掉。

写入侧本来就有乐观锁（`assert_persistence_baseline`），但它只比对**被写的那一行**。
上游交接是另一行，改它不会让审查运行这一行的基线失配，于是依据已经过时的结论
仍会作为最新结果保存。这里在同一个事务内把上游再读一遍，不一致就让整笔回滚。

只拦"把结论摆到人面前"的那几种状态。失败、取消、以及记录"来源已变、需重新核对"
本身都要能写下去——把它们一起拦掉，系统就没法记录自己已经过时了。
"""
from __future__ import annotations

# 运行在这些状态下写入，等于宣布"这是这条审查的最新结论"。
RESULT_BEARING_STATUSES = frozenset({"waiting_human_review", "waiting_human_input"})


class HandoffSourceChangedDuringCommit(RuntimeError):
    """来源在执行期间变了，结论不能作为最新结果保存。"""

    reason = "HANDOFF_SOURCE_CHANGED_DURING_COMMIT"

    def __init__(self, run_id: str, detail: str) -> None:
        super().__init__(f"handoff source changed during commit (run={run_id}, detail={detail})")
        self.run_id = run_id
        self.detail = detail


def _reason_of(exc: BaseException) -> str:
    return str(getattr(exc, "reason", "") or exc.__class__.__name__)


def assert_handoff_sources_unchanged(connection, dirty_documents, tenant_id, *, review_run_collection="review_runs"):
    """在当前事务里复核每一条待写结论的交接来源。

    `dirty_documents` 是仓库算出的待写集合，键为 (collection, object_id)，
    值为 (文档, 序列化载荷)。只看审查运行、且带交接快照、且状态是结论态的那几条。
    """
    from libs.db.review_handoff_loading import load_handoff_rows
    from libs.review_document_scope import ensure_document_sources

    for (collection_name, object_id), value in dirty_documents.items():
        if collection_name != review_run_collection:
            continue
        document = value[0] if isinstance(value, tuple) else value
        if not isinstance(document, dict) or "handoffInputsSnapshot" not in document:
            continue
        if str(document.get("status") or "") not in RESULT_BEARING_STATUSES:
            continue
        rows, _, _ = load_handoff_rows(connection, document, tenant_id)
        current: dict[str, list] = {"review_runs": [document]}
        for collection, _object_id, payload in rows:
            current.setdefault(collection, []).append(payload)
        try:
            ensure_document_sources(document, current)
        except Exception as exc:
            # ensure_document_sources 把校验失败统一包成 REVIEW_INPUT_CHANGED_RECREATE_RUN，
            # 那个码用在"发起前来源就变了"。提交阶段要能和它区分开：这一笔是结论已经算完、
            # 落库时才发现依据过时，处置不同——运维要知道该重新发起而不是重试写入。
            raise HandoffSourceChangedDuringCommit(str(object_id), _reason_of(exc)) from exc
