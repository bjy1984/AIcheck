"""2026-08-14 角色权限审计的修复（F-1 / F-2 / F-3 / F-4）。

审计原始记录见 docs/audit/2026-08-14-角色权限审计.md。
"""

from __future__ import annotations

from libs.todo_visibility import todo_visible_to, visible_todos

# ── F-3：待办按人过滤 ────────────────────────────────────────────────
#
# 实测：监检方与施工方 GET /api/todos 拿到逐条相同的 20 条。
# 接口声明了 role 参数却从未使用——一个声明了却不生效的参数，
# 比没有这个参数更坏：调用方以为自己筛过了。

INSPECTOR = {"username": "inspection", "name": "侧写验证7341", "displayName": "张工"}
CONTRACTOR = {"username": "contractor", "name": "李工", "displayName": "李工"}


def test_只看得到指派给自己的待办():
    todos = [
        {"id": "TODO-001", "assigneeName": "张工"},
        {"id": "TODO-002", "assigneeName": "李工"},
    ]
    assert [t["id"] for t in visible_todos(todos, INSPECTOR, "inspection")] == ["TODO-001"]
    assert [t["id"] for t in visible_todos(todos, CONTRACTOR, "contractor")] == ["TODO-002"]


def test_显示名与账号名都要认():
    """库里 assigneeName 用的是显示名（张工），而账号上还有 name
    （侧写验证7341）与 username（inspection）——历史数据三种都出现过。"""
    for value in ("张工", "侧写验证7341", "inspection"):
        assert todo_visible_to({"assigneeName": value}, INSPECTOR, "inspection")


def test_未指派的待办谁都看得见():
    """它不属于任何人，藏起来只会让事情停在那里没人做。

    这是刻意选的 fail-open 方向：多看一条的代价，小于流程静默卡住。
    """
    assert todo_visible_to({"id": "T", "assigneeName": ""}, CONTRACTOR, "contractor")
    assert todo_visible_to({"id": "T"}, CONTRACTOR, "contractor")


def test_管理员看全部():
    """admin 的职责就是看全局，藏起来反而没法排查。"""
    todos = [{"assigneeName": "张工"}, {"assigneeName": "李工"}]
    assert len(visible_todos(todos, {"username": "admin"}, "admin")) == 2


def test_脏数据不炸():
    assert visible_todos(None, INSPECTOR, "inspection") == []
    assert visible_todos([None, 3], INSPECTOR, "inspection") == []  # type: ignore[list-item]
    # 认不出请求者就不过滤——藏光比多看一条危险，流程会静默停住
    assert todo_visible_to({"assigneeName": "张工"}, None, "contractor") is True
    assert todo_visible_to({"assigneeName": "张工"}, {}, "contractor") is True


# ── F-1 / F-4：同一份数据的多个入口要用同一道闸 ──────────────────────


def test_reasoning_logs_三个入口都接了审查过程守卫():
    """实测：/nodes/{n}/ai-runs 对施工方 403，而 /reasoning/logs 返回 code 0，
    里面是同一个 ai_runs 集合——suggestion.result、opinionDraft、
    reasoningProcess 一应俱全。一道门拦住、另一道敞着，等于没拦。"""
    import pathlib

    source = pathlib.Path(__file__).resolve().parents[1] / "apps" / "api" / "routes.py"
    text = source.read_text(encoding="utf-8")
    for marker in (
        'def reasoning_logs(',
        'def reasoning_log_detail(',
        'def reasoning_log_evidence(',
    ):
        start = text.index(marker)
        body = text[start : start + 900]
        assert "review_process_read_error" in body, f"{marker} 少了审查过程守卫"


def test_监检工作过程端点都接了守卫():
    """review-log / date-compare / fact-corrections 是监检的底稿，
    被检方读到它等于看审查方的工作过程。

    另外四个（standards / rules/current-version / live-status / evidence-chain）
    **有意不动**：施工方需要知道自己要满足哪些条款，一刀封会打断正常流程。
    那四个需要业务确认，记在审计文档里。
    """
    import pathlib

    source = pathlib.Path(__file__).resolve().parents[1] / "apps" / "api" / "routes.py"
    text = source.read_text(encoding="utf-8")
    for endpoint in ("review-log", "date-compare", "fact-corrections"):
        # 必须定位 GET 那条——fact-corrections 同时有 POST（人工修正写入），
        # 第一次写这条测试时命中了 POST，才发现要分开看两种方法。
        idx = text.index(f'@router.get("/projects/{{project_id}}/inspection/nodes/{{node_id}}/{endpoint}")')
        assert "review_process_read_error" in text[idx : idx + 1500], f"{endpoint} GET 少了守卫"


def test_写入路径由中间件按路由推导动作码():
    """查 F-4 时顺带核实过一次，结论是安全的，钉在这里免得下次再怀疑一遍。

    mutation_guard 里的 `if action_code and ...` 只在客户端主动发
    X-Action-Code 时才生效，单看它像是可以绕过。真正的强制在中间件
    inferred_action_error：动作码从**路由表**推导（libs/security/actions.py），
    不信任请求头，再比对 repo.role_actions(role)。
    施工方没有 review:save，POST fact-corrections 就是 403。
    """
    import pathlib

    main = (pathlib.Path(__file__).resolve().parents[1] / "apps" / "api" / "main.py").read_text(
        encoding="utf-8"
    )
    idx = main.index("def inferred_action_error(")
    body = main[idx : idx + 1200]
    assert "required_action_for_request(request.method, request.url.path)" in body
    assert "allowed_actions" in body

    actions = (
        pathlib.Path(__file__).resolve().parents[1] / "libs" / "security" / "actions.py"
    ).read_text(encoding="utf-8")
    assert "fact-corrections$" in actions and "review:save" in actions


# ── F-2：用户目录最小投影 ────────────────────────────────────────────


def test_非管理员只拿得到身份识别字段():
    """mobile / status / lastLoginAt / mustChangePassword 不该给被检方。

    mobile 当前为空只是测试数据没填——字段在契约里开放，真实部署录入手机号后
    被检方就拿到了监检人员的联系方式；mustChangePassword 还能指出哪些账号
    仍在用初始口令。
    """
    import pathlib

    source = pathlib.Path(__file__).resolve().parents[1] / "apps" / "api" / "routes.py"
    text = source.read_text(encoding="utf-8")
    idx = text.index("_PUBLIC_USER_FIELDS")
    block = text[idx : idx + 300]
    for allowed in ("id", "username", "displayName", "role", "orgName"):
        assert f'"{allowed}"' in block
    for denied in ("mobile", "mustChangePassword", "lastLoginAt", "status"):
        assert f'"{denied}"' not in block, f"{denied} 不该在非管理员可见字段里"
