"""待办的可见范围。

## 问题

2026-08-14 审计实测：监检方与施工方 `GET /api/todos` 拿到的是**同一批 20 条，
ID 逐条相同**（TODO-001、TODO-002、TODO-0F5E781B…）。待办里带着「谁该做什么」，
等于把各方的工作安排互相公开。

代码上的原因很直白——接口声明了 `role` 参数却从未使用：

    def list_todos(request, role: str | None = None, projectId=None, status=None, ...):
        items = [... if record_visible_for_request(request, item)]   # 只过滤项目范围
        if projectId: ...
        if status: ...
        # role 一次都没被读过

一个声明了却不生效的参数，比没有这个参数更坏：调用方以为自己筛过了。

## 口径

待办记录里**没有 `assigneeRole`**，只有 `assigneeName`（线上 63 条：61 条归
「张工」即监检，各 1 条归施工方与另一人）。所以按**人**匹配，不按角色匹配。

未指派的待办对所有人可见——它不属于任何人，藏起来只会让事情没人做。
这是刻意选择的 fail-open 方向：待办漏看的代价是有人多看一条，
而错误地藏起来的代价是流程停在那里没人知道。
"""

from __future__ import annotations

from typing import Any


def _names_of(user: dict[str, Any] | None) -> set[str]:
    """一个人可能被写成的几种名字。

    库里 assigneeName 用的是显示名（「张工」），而账号上同时还有
    name（「侧写验证7341」）与 username（「inspection」）——三者都可能出现在
    历史数据里，都要认。
    """
    data = user if isinstance(user, dict) else {}
    return {
        str(data.get(key) or "").strip()
        for key in ("displayName", "name", "username", "id")
        if str(data.get(key) or "").strip()
    }


def todo_visible_to(todo: dict[str, Any], user: dict[str, Any] | None, role: str = "") -> bool:
    """这条待办该不该给这个人看。

    admin 看全部——它的职责就是看全局，藏起来反而没法排查。
    """
    if str(role or "") == "admin":
        return True
    names = _names_of(user)
    if not names:
        # 认不出请求者是谁（未开启鉴权、或令牌没有对应账号记录）就不过滤。
        # 按身份过滤的前提是知道身份；不知道还硬筛，结果是待办整个清空——
        # 第一版就是这么写的，测试环境当场 0 条。
        # 藏光比多看一条危险得多：流程会静默停住，而没人知道为什么。
        return True
    assignee = str((todo or {}).get("assigneeName") or "").strip()
    if not assignee:
        return True  # 未指派：不属于任何人，谁都能看见
    return assignee in names


def visible_todos(
    todos: list[dict[str, Any]], user: dict[str, Any] | None, role: str = ""
) -> list[dict[str, Any]]:
    return [item for item in todos or [] if isinstance(item, dict) and todo_visible_to(item, user, role)]
