"""待办与消息：谁该做什么、谁该知道什么（2026-11-04）。

见 libs/notifications.py 模块头。这里钉住：
- 待办按角色投递、做完由业务动作自动关掉，徽标只数还要办的；
- 消息按角色投递、已读按人记、同一件事不刷屏；
- 主链路每一步都给对的人发了对的东西（上传、提交、退回、补正、下结论）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs import notifications as nt
from libs.db.repository import repo
from libs.todo_visibility import todo_visible_to
from tests.test_main_chain_e2e import (
    CONTRACTOR,
    INSPECTION,
    NODE_ID,
    PROJECT_ID,
    bind_to_node,
    ok,
    upload_document,
)

client = TestClient(app)
OWNER = {"X-Dev-Role": "owner", "X-Dev-User": "USER-OWNER-001", "X-Role": "owner"}


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


# ── 纯函数 ─────────────────────────────────────────────────────────────


def test_待办按角色投递_待分配不再让人看不见():
    state: dict = {}
    todo = nt.open_todo(state, kind="submission_review", project_id="P1", title="待审", target_type="submission",
                        target_id="SUB-1", assignee_role="inspection", assignee_name="待分配", node_id=3)
    assert todo["assigneeName"] == "" and todo["assigneeRole"] == "inspection"
    assert todo_visible_to(todo, {"displayName": "后来的监检"}, "inspection"), "同角色的人都看得见"
    assert not todo_visible_to(todo, {"displayName": "施工方甲"}, "contractor"), "别的角色看不见"
    assert todo_visible_to(todo, {"displayName": "管理员"}, "admin")
    legacy = {"assigneeName": "待分配", "status": "待处理"}
    assert todo_visible_to(legacy, {"displayName": "张工"}, "inspection"), "老待办的「待分配」当成未指派"


def test_多节点提交的待办要每个节点都下结论才关():
    state: dict = {}
    nt.open_todo(state, kind="submission_review", project_id="P1", title="待审", target_type="submission",
                 target_id="SUB-1", assignee_role="inspection", node_id=3, node_ids=[3, 4])
    nt.node_concluded(state, project_id="P1", node_id=3, result="满足要求")
    assert nt.pending(state["todos"]), "只审完一个节点，待办还开着"
    nt.node_concluded(state, project_id="P1", node_id=4, result="需补正")
    assert not nt.pending(state["todos"]) and state["todos"][0]["closedBy"] == "系统"


def test_同一件事的消息更新原消息并重新标未读_已读按人记():
    state: dict = {}
    first = nt.notify(state, kind="node_conclusion", project_id="P1", title="结论 A", content="a",
                      recipient_roles=("contractor", "owner"), dedupe_key="conclusion:P1:3")
    assert nt.mark_read(first, "U-1") and not nt.mark_read(first, "U-1"), "第二次不算变化"
    assert nt.message_view(first, "U-1")["read"] and not nt.message_view(first, "U-2")["read"]
    again = nt.notify(state, kind="node_conclusion", project_id="P1", title="结论 B", content="b",
                      recipient_roles=("contractor", "owner"), dedupe_key="conclusion:P1:3")
    assert again is first and len(state["messages"]) == 1 and first["title"] == "结论 B"
    assert not nt.message_view(first, "U-1")["read"], "结论变了，要重新提醒"
    assert nt.message_visible_to(first, "owner") and not nt.message_visible_to(first, "inspection")
    assert nt.message_read_by({"read": True}, "U-9"), "老消息的全局已读视作所有人已读"


def test_上传按天合并成一条():
    state: dict = {}
    nt.uploads_received(state, project_id="P1", uploader_role="contractor", file_count=2)
    nt.uploads_received(state, project_id="P1", uploader_role="contractor", file_count=3)
    assert len(state["messages"]) == 1 and "5 份" in state["messages"][0]["title"]
    assert nt.uploads_received(state, project_id="P1", uploader_role="inspection", file_count=1) is None


# ── 主链路：每一步给对的人发对的东西 ────────────────────────────────────


def todos_of(headers: dict) -> list[dict]:
    data = ok(client.get(f"/api/todos?projectId={PROJECT_ID}&pageSize=200", headers=headers), "待办")
    return [item for item in data["items"] if item.get("status") == "待处理"]


def messages_of(headers: dict) -> list[dict]:
    return ok(client.get(f"/api/messages?projectId={PROJECT_ID}&pageSize=200", headers=headers), "消息")["items"]


def kinds(items: list[dict]) -> set[str]:
    return {str(item.get("kind")) for item in items if item.get("kind")}


def test_主链路的待办和消息():
    document_id = upload_document("焊工证-通知.pdf", "notify-first")
    assert "uploads_received" in kinds(messages_of(INSPECTION)), "施工方传了资料，监检要知道有东西进来"
    binding_id = bind_to_node(document_id, "notify-first")
    ok(client.post(f"/api/projects/{PROJECT_ID}/submissions",
                   headers={**CONTRACTOR, "Idempotency-Key": "notify-submit", "If-Match": "*"},
                   json={"nodeIds": [NODE_ID], "bindingIds": [binding_id], "batchName": "通知链路"}), "提交")
    assert "submission_review" in kinds(todos_of(INSPECTION))
    assert "submission_review" not in kinds(todos_of(CONTRACTOR)), "监检的活不该出现在施工方的待办里"

    ok(client.post(f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/actions/return-correction",
                   headers={**INSPECTION, "Idempotency-Key": "notify-return", "If-Match": "*"},
                   json={"reason": "焊工证持证项目未覆盖本工程焊接方法，请补充。", "bindingIds": [binding_id]}), "退回")
    assert "submission_review" not in kinds(todos_of(INSPECTION)), "退回了就算审完这一轮"
    assert "rectification" in kinds(todos_of(CONTRACTOR))
    assert "node_correction" in kinds(messages_of(OWNER)), "建设方要知道节点被退回"

    rectification = next(item for item in repo.state["rectifications"]
                         if item.get("projectId") == PROJECT_ID and int(item.get("nodeId") or 0) == NODE_ID
                         and item.get("status") == "待反馈")
    new_binding_id = bind_to_node(upload_document("补充焊工证-通知.pdf", "notify-second"), "notify-second")
    ok(client.post(f"/api/projects/{PROJECT_ID}/rectifications",
                   headers={**CONTRACTOR, "Idempotency-Key": "notify-rectify", "If-Match": "*"},
                   json={"nodeId": NODE_ID, "rectificationId": rectification["id"], "bindingIds": [new_binding_id],
                         "comment": "已补充。"}), "补正")
    assert "rectification" not in kinds(todos_of(CONTRACTOR)), "交了补正，退回补正的待办自己关掉"
    assert "resubmission_review" in kinds(todos_of(INSPECTION))

    from test_contract import seed_confirmed_node_24_evidence

    ok(client.post(f"/api/projects/{PROJECT_ID}/inspection/nodes/{NODE_ID}/review-opinions",
                   headers={**INSPECTION, "Idempotency-Key": "notify-opinion", "If-Match": "*"},
                   json={"result": "满足要求", "opinion": "补正后资料齐全。",
                         "evidenceLinkIds": seed_confirmed_node_24_evidence(PROJECT_ID)}), "结论")
    assert "resubmission_review" not in kinds(todos_of(INSPECTION)), "下了结论，复审待办自己关掉"
    contractor_conclusion = next(item for item in messages_of(CONTRACTOR) if item.get("kind") == "node_conclusion")
    assert "满足要求" in contractor_conclusion["title"] and not contractor_conclusion["read"]
    assert "node_conclusion" not in kinds(messages_of(INSPECTION)), "监检自己下的结论不用再通知自己"

    # 已读按人记：施工方点了已读，建设方那边还是未读
    ok(client.post(f"/api/messages/{contractor_conclusion['id']}/read",
                   headers={**CONTRACTOR, "Idempotency-Key": "notify-read"}), "标已读")
    assert next(item for item in messages_of(CONTRACTOR) if item["id"] == contractor_conclusion["id"])["read"]
    assert not next(item for item in messages_of(OWNER) if item["id"] == contractor_conclusion["id"])["read"]

    # 徽标：待办只数还要办的；未读消息数按人、不受「最多带 5 条」限制
    summary = ok(client.get(f"/api/projects/{PROJECT_ID}/workbench/summary?role=contractor", headers=CONTRACTOR), "摘要")
    todo_metric = next(item for item in summary["metrics"] if item["key"] == "todo")
    assert todo_metric["value"] == len(todos_of(CONTRACTOR))
    assert summary["messageUnreadCount"] == sum(1 for item in messages_of(CONTRACTOR) if not item["read"])
