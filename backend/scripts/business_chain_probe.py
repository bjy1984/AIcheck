#!/usr/bin/env python3
"""部署后业务链探针：断言内容对不对，而不是接口通不通。

## 为什么要它

现有 e2e 有 2400 多行，全是路由、布局、响应式、错误映射——「页面打得开」。
而 2026-08-13 这一轮线上排查里找到的问题，没有一个是页面打不开：

- Office 预览接口返回 200 和一个合法 URL，取回是 404（对象根本没写进去）；
- 预览 URL 指向 http://127.0.0.1:19000，那是服务器自己的回环，浏览器到不了；
- 表格列名按字典序返回（jsonb 不保留键序），「备注」排到了第一列；
- 证据裁减把两份资料全裁光，却报告「裁减成功」；
- 提示词里 41% 的预算被与本节点无关的工具目录占掉。

它们的共同点：**所有状态码都是 200，所有单测都是绿的**。只有真的去看返回的
内容才发现不对。这个脚本就是把那些手工核对固化下来。

## 每一条检查都对应一个真实发生过的故障

不是想象中的风险清单。加新检查前先问：这条挡住过什么？挡不住就别加——
探针越长越没人看，而没人看的探针等于不存在。

## 用法

    python -m scripts.business_chain_probe --base-url http://127.0.0.1:8081 \\
        --username inspection --password-env AICHECK_PROBE_PASSWORD

口令只从环境变量读，不接受命令行参数：命令行会进 shell 历史和进程表。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

TIMEOUT_SECONDS = 180


class ProbeFailure(RuntimeError):
    """一条检查没通过。"""


def call_api(
    base_url: str, path: str, token: str | None = None, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8") if payload else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


def fetch_bytes(base_url: str, url: str, token: str | None = None) -> bytes:
    target = url if url.startswith("http") else base_url.rstrip("/") + url
    request = urllib.request.Request(
        target, headers={"Authorization": f"Bearer {token}"} if token else {}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def login(base_url: str, username: str, password: str) -> str:
    result = call_api(base_url, "/api/auth/login", payload={"username": username, "password": password})
    token = ((result or {}).get("data") or {}).get("token")
    if not token:
        raise ProbeFailure(f"登录失败：{result.get('message') or result.get('code')}")
    return str(token)


def check_office_preview_actually_serves_a_pdf(
    base_url: str, token: str, project_id: str, documents: list[dict[str, Any]]
) -> str:
    """Office 预览必须真的取得到 PDF 字节。

    挡住过：接口返回 200 + 合法 URL，而对象根本没写进对象存储（缓存判据用的是
    「能否签发 URL」，而签发是纯计算、从不校验存在）；以及 URL 指向服务器回环，
    浏览器取不到。两次都是所有状态码正常，只有真去取才发现是空的。
    """
    office = next(
        (
            item
            for item in documents
            if str(item.get("fileName") or "").lower().endswith((".docx", ".doc", ".xlsx", ".xls"))
        ),
        None,
    )
    if not office:
        return "跳过（项目内没有 Office 资料）"
    document_id = office.get("documentId") or office.get("id")
    result = call_api(
        base_url, f"/api/projects/{project_id}/documents/{document_id}/office-preview", token
    )
    if result.get("code") != 0:
        message = str(result.get("message") or "")
        if "没有可用的存储对象" in message:
            # 这份资料压根没落存储（种子数据里有这种），不是转换链路回归。
            # 探针要分得清「环境本来就没有」和「功能坏了」，否则每次都红，
            # 红久了就没人看了。
            return f"跳过（{office.get('fileName')} 没有存储对象）"
        raise ProbeFailure(f"Office 预览接口失败：{message}")
    url = str(((result.get("data") or {}).get("url")) or "")
    if not url:
        raise ProbeFailure("Office 预览没有返回地址")
    if "127.0.0.1" in url or "localhost" in url:
        raise ProbeFailure(f"预览地址指向服务器回环，浏览器取不到：{url[:60]}")
    data = fetch_bytes(base_url, url, token)
    if not data.startswith(b"%PDF-"):
        raise ProbeFailure(f"预览地址取回的不是 PDF（前 8 字节 {data[:8]!r}）")
    return f"{office.get('fileName')} → {len(data)} 字节 PDF"


def check_table_column_order_is_not_alphabetical(
    base_url: str, token: str, project_id: str, documents: list[dict[str, Any]]
) -> str:
    """表格列名要来自表头单元格，不是字典键序。

    挡住过：state 存在 Postgres 的 jsonb 列，而 jsonb 不保留对象键序（按键长 +
    字节序重排）。焊材表存进去是「序号 / 管道材料 / …」，取回来「备注」排到了
    第一列——监检对着这样的参数表核不了任何东西。
    """
    checked = 0
    for item in documents[:12]:
        document_id = item.get("documentId") or item.get("id")
        detail = (
            call_api(base_url, f"/api/projects/{project_id}/documents/{document_id}", token).get("data")
            or {}
        )
        for table in ((detail.get("ocrStructured") or {}).get("tables")) or []:
            names = [str(name) for name in table.get("columnNames") or []]
            if len(names) < 3 or not table.get("headerReliable"):
                continue
            checked += 1
            if names == sorted(names):
                raise ProbeFailure(
                    f"表格列序疑似字典序（jsonb 键序泄漏）：{names[:5]}"
                )
    return f"检查了 {checked} 张有表头的表" if checked else "跳过（没有带可信表头的表格）"


def nodes_with_failed_ai(base_url: str, token: str, project_id: str) -> list[int]:
    """有 AI 失败记录的节点号。

    走 audit-overview 一次拿全项目的审计项状态，直接筛出失败的节点——而不是
    逐个节点拉包再看。这两版的差别不只是快慢：

    第一版按 tree 平铺找 nodes（实际结构是 groups[].nodes），一个都没枚举到；
    第二版枚举对了，但只扫前 20 个节点，而线上那条失败在节点 24。两次都表现为
    「跳过（当前没有失败运行）」——探针悄悄跳过检查，比没有探针更糟：
    它让人以为已经验过了。
    """
    failed: set[int] = set()
    page = 1
    while True:
        result = call_api(
            base_url,
            f"/api/projects/{project_id}/inspection/audit-overview?page={page}&pageSize=50",
            token,
        )
        data = result.get("data") or {}
        items = data.get("items") or []
        for entry in items:
            node_id = ((entry.get("node") or {}).get("nodeId"))
            if node_id is None:
                continue
            for audit_item in entry.get("items") or []:
                if str(audit_item.get("status") or "") in {"执行失败", "failed", "failed_to_start"}:
                    failed.add(int(node_id))
                    break
        if len(items) < 50 or page * 50 >= int(data.get("total") or 0):
            break
        page += 1
    return sorted(failed)


def check_failed_ai_runs_explain_themselves(
    base_url: str, token: str, project_id: str
) -> str:
    """失败的 AI 运行必须给出可读归因，且不是模板串。

    挡住过：界面只显示「异常」两个字，而库里躺着完整报错；以及我自己写的第一版
    归因——拿 ai_run 上写死的模板串「Temporal/LangGraph 审查编排执行失败。」
    去分类，把「资料超出模型上下文预算」误诊成「编排服务连不上」，会让人去查
    一个好好的服务。
    """
    node_ids = nodes_with_failed_ai(base_url, token, project_id)
    inspected = 0
    for node_id in node_ids:
        package = (
            call_api(base_url, f"/api/projects/{project_id}/nodes/{node_id}/package", token).get("data")
            or {}
        )
        for run in package.get("aiRuns") or []:
            if str(run.get("status")) not in {"失败", "failed", "failed_to_start"}:
                continue
            inspected += 1
            failure = run.get("failure")
            if not failure:
                raise ProbeFailure(f"节点 {node_id} 的失败运行没有归因信息")
            if not failure.get("nextStep"):
                raise ProbeFailure(f"节点 {node_id} 的失败归因没有给出下一步")
            if "Temporal/LangGraph 审查编排执行失败" in str(failure.get("detail") or ""):
                raise ProbeFailure(
                    f"节点 {node_id} 的归因取自模板串而非真实异常——真实原因在关联 ReviewRun 上"
                )
    return f"检查了 {inspected} 次失败运行" if inspected else "跳过（当前没有失败运行）"


def check_weak_passwords_are_rejected(base_url: str, username: str) -> str:
    """用户名当口令必须被拒。

    挡住过：造号脚本在缺少 AICHECK_BOOTSTRAP_PASSWORD_* 时回退成「用户名即口令」，
    而部署验证只测「能不能登录成功」，回退了也全绿。
    """
    result = call_api(base_url, "/api/auth/login", payload={"username": username, "password": username})
    if result.get("code") == 0:
        raise ProbeFailure(f"弱口令未被拒绝：{username} 的口令等于用户名")
    return "弱口令已拒"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--username", default="inspection")
    parser.add_argument(
        "--password-env",
        default="AICHECK_PROBE_PASSWORD",
        help="读口令的环境变量名。口令不走命令行——那会进 shell 历史和进程表。",
    )
    parser.add_argument("--project-id", default="")
    args = parser.parse_args()

    password = os.getenv(args.password_env, "")
    if not password:
        print(f"缺少口令：请设置环境变量 {args.password_env}", file=sys.stderr)
        return 2

    try:
        token = login(args.base_url, args.username, password)
    except Exception as exc:  # noqa: BLE001 — 登录失败就没法继续，原样报出来
        print(f"✗ 登录：{exc}", file=sys.stderr)
        return 1

    project_id = args.project_id
    documents: list[dict[str, Any]] = []
    if project_id:
        documents = (
            call_api(args.base_url, f"/api/projects/{project_id}/documents", token).get("data") or {}
        ).get("items") or []
    else:
        # 挑资料最多的项目，不是第一个。接进部署时踩过：默认取首个项目，
        # 而它恰好 0 份资料，四条检查全跳过却报全绿——探针在一个空项目上
        # 什么也证明不了，却让人以为验过了。
        projects = (call_api(args.base_url, "/api/projects", token).get("data") or {}).get("items") or []
        if not projects:
            print("✗ 没有可探测的项目", file=sys.stderr)
            return 1
        for candidate in projects:
            candidate_id = str(candidate.get("id") or "")
            if not candidate_id:
                continue
            items = (
                call_api(args.base_url, f"/api/projects/{candidate_id}/documents", token).get("data")
                or {}
            ).get("items") or []
            if len(items) > len(documents):
                project_id, documents = candidate_id, items
        if not project_id:
            project_id = str(projects[0].get("id"))

    checks = [
        ("弱口令拒绝", lambda: check_weak_passwords_are_rejected(args.base_url, args.username)),
        (
            "Office 预览真能取到 PDF",
            lambda: check_office_preview_actually_serves_a_pdf(
                args.base_url, token, project_id, documents
            ),
        ),
        (
            "表格列序非字典序",
            lambda: check_table_column_order_is_not_alphabetical(
                args.base_url, token, project_id, documents
            ),
        ),
        (
            "AI 失败可归因",
            lambda: check_failed_ai_runs_explain_themselves(args.base_url, token, project_id),
        ),
    ]

    failed = 0
    skipped = 0
    print(f"业务链探针 · 项目 {project_id} · 资料 {len(documents)} 份")
    for name, check in checks:
        try:
            detail = check()
        except ProbeFailure as exc:
            print(f"  ✗ {name}：{exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001 — 探针自身出错也要报出来，不能静默跳过
            print(f"  ✗ {name}：探针异常 {type(exc).__name__}: {exc}")
            failed += 1
        else:
            if detail.startswith("跳过"):
                skipped += 1
            print(f"  ✓ {name}：{detail}")

    # 全跳过不等于全通过：那说明这个环境里没有可验的数据，探针什么也没证明。
    # 报绿会让人以为验过了——这正是探针本身要防的那类错觉。
    if not failed and skipped >= len(checks) - 1:
        print(f"  ! 有 {skipped}/{len(checks)} 条因缺少数据被跳过——本次探测未能证明任何东西")
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
