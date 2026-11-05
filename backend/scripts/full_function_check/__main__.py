"""AIcheck 全功能验收脚本。

两种跑法：

  # 进程内（默认）：临时 SQLite + 演示数据 + 演示账号，真实登录、真实路由；
  # OCR 工人、AI 复核派发用替身。不需要起服务，不连生产库，跑完删临时目录。
  .venv/bin/python -m scripts.full_function_check

  # 打一个已经在跑的服务（默认只认本机地址；写操作只在本机地址上做）
  .venv/bin/python -m scripts.full_function_check --base-url http://127.0.0.1:8000

  # 只跑某几个模块 / 用例
  .venv/bin/python -m scripts.full_function_check --only INSP,CONT-03

  # 生成用例文档（Markdown + Excel 可开的 CSV）
  .venv/bin/python -m scripts.full_function_check --catalog ../docs/testing/全功能测试用例.md

账号口令：进程内和本机地址用演示账号；别的地址必须用环境变量
AICHECK_FULLCHECK_PASSWORD 和 AICHECK_FULLCHECK_USER_<ROLE> 提供，脚本不会打印它们。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
ROLES = ("inspection", "contractor", "ndt", "owner", "admin", "fde")
MODE_LABELS = {"api": "接口自动", "ui": "浏览器自动", "manual": "人工"}


def prepare_in_process_env(workdir: Path) -> None:
    """进程内模式的环境：必须在 import apps.api.main 之前设好。"""
    for key in (
        "AICHECK_DATABASE_URL",
        "DATABASE_URL",
        "AICHECK_REDIS_URL",
        "AICHECK_MINIO_ENDPOINT",
    ):
        os.environ.pop(key, None)
    os.environ.update(
        {
            "AICHECK_ENABLE_DEMO_DATA": "true",
            "AICHECK_ENABLE_DEMO_USERS": "true",
            "AICHECK_REQUIRE_AUTH": "true",
            "AICHECK_REQUIRE_IF_MATCH": "true",
            "AICHECK_STRICT_PRODUCTION": "false",
            "AICHECK_SQLITE_DISABLE": "false",
            "AICHECK_SQLITE_PATH": str(workdir / "state.sqlite"),
            "AICHECK_SKILL_PACKAGE_DIR": str(workdir / "skill_package"),
            "AICHECK_OCR_PROVIDER_MODE": "local",
            "AICHECK_OCR_DEFAULT_PROVIDER": "local",
            "AICHECK_CERT_PLATFORM_VERIFY": "off",
            "AICHECK_EMBEDDING_FORCE_OFFLINE_HASH": "true",
            "AICHECK_LLM_RATE_LIMIT_BACKOFF_SECONDS": "0",
        }
    )


def in_process_transport(workdir: Path) -> tuple[Any, list[Path]]:
    prepare_in_process_env(workdir)
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    import warnings

    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from fastapi.testclient import TestClient

    from apps.api import main, routes

    # 上传落盘目录写死在仓库 output/ 下，且存储键要求在仓库目录内（local://相对路径）。
    # 进程内跑改到 output/ 下一个独立子目录（整个 output/ 已被 git 忽略），跑完删掉。
    suffix = workdir.name
    upload_dirs = [
        Path(routes.WORKSPACE_ROOT) / "output" / "document_uploads" / f".fullcheck-{suffix}",
        Path(routes.WORKSPACE_ROOT) / "output" / "knowledge_uploads" / f".fullcheck-{suffix}",
    ]
    routes.DOCUMENT_UPLOAD_ROOT, routes.KNOWLEDGE_UPLOAD_ROOT = upload_dirs
    return TestClient(main.app, base_url="http://127.0.0.1:8000"), upload_dirs


def http_transport(base_url: str, timeout: float) -> Any:
    import httpx

    return httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, follow_redirects=False)


def demo_password() -> str:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from libs.security.auth import SHARED_TEST_PASSWORD

    return SHARED_TEST_PASSWORD


def usernames_from_env() -> dict[str, str]:
    return {role: os.getenv(f"AICHECK_FULLCHECK_USER_{role.upper()}", role) for role in ROLES}


def select_cases(registry: list[Any], only: str) -> list[Any]:
    if not only:
        return list(registry)
    wanted = [token.strip().upper() for token in only.split(",") if token.strip()]
    return [
        case
        for case in registry
        if any(case.id == token or case.prefix == token for token in wanted)
    ]


def run_cases(ctx: Any, cases: list[Any], *, verbose: bool) -> list[dict[str, Any]]:
    from scripts.full_function_check.base import CaseFailed, CaseSkipped

    results: list[dict[str, Any]] = []
    for case in cases:
        if case.mode != "api":
            continue
        started = time.perf_counter()
        status, detail = "PASS", ""
        try:
            if case.in_process_only and not ctx.in_process:
                raise CaseSkipped("只在进程内模式跑（需要替身或会改动数据）")
            if case.writes and not ctx.allow_writes:
                raise CaseSkipped(
                    "会写数据；当前目标不允许写（加 --allow-writes 前先确认不是生产）"
                )
            case.fn(ctx)
        except CaseSkipped as exc:
            status, detail = "SKIP", str(exc)
        except CaseFailed as exc:
            status, detail = "FAIL", str(exc)
        except Exception as exc:  # noqa: BLE001 - 用例代码自身出错也要记一条，不能让整轮中断
            status = "ERROR"
            detail = f"{type(exc).__name__}: {exc}"
            if verbose:
                detail += "\n" + "".join(traceback.format_exc(limit=6))
        finally:
            ctx.restore_patches()
        elapsed = time.perf_counter() - started
        results.append(
            {
                "id": case.id,
                "module": case.module,
                "title": case.title,
                "role": case.role,
                "priority": case.priority,
                "status": status,
                "detail": detail,
                "seconds": round(elapsed, 3),
            }
        )
        mark = {"PASS": "通过", "FAIL": "失败", "ERROR": "出错", "SKIP": "跳过"}[status]
        print(f"[{mark}] {case.id} {case.title} ({elapsed:.2f}s)", flush=True)
        if detail and status != "PASS":
            for line in detail.splitlines():
                print(f"        {line}", flush=True)
    return results


def write_report(results: list[dict[str, Any]], out_dir: Path, meta: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    counts = Counter(item["status"] for item in results)
    lines = [
        "# 全功能验收结果",
        "",
        f"- 时间：{meta['finishedAt']}",
        f"- 目标：{meta['target']}",
        f"- 通过 {counts['PASS']}，失败 {counts['FAIL']}，出错 {counts['ERROR']}，跳过 {counts['SKIP']}",
        "",
        "| 编号 | 用例 | 结果 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for item in results:
        detail = item["detail"].splitlines()[0] if item["detail"] else ""
        lines.append(
            f"| {item['id']} | {item['title']} | {item['status']} | {detail.replace('|', '/')} |"
        )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def cell(text: str) -> str:
    return text.replace("|", "／").replace("\n", " ")


def render_catalog(registry: list[Any]) -> str:
    from scripts.full_function_check.base import MODULES, ROLE_LABELS

    by_mode = Counter(case.mode for case in registry)
    by_priority = Counter(case.priority for case in registry)
    lines = [
        "# AIcheck 全功能测试用例",
        "",
        (
            "> 本文件由 `backend/scripts/full_function_check` 生成，不要手改。"
            "要增删改用例，改 `backend/scripts/full_function_check/cases_*.py`，再重新生成："
        ),
        "> `cd backend && .venv/bin/python -m scripts.full_function_check --catalog ../docs/testing/全功能测试用例.md`",
        "",
        (
            f"共 {len(registry)} 条：接口自动 {by_mode['api']} 条、浏览器自动 {by_mode['ui']} 条、人工 {by_mode['manual']} 条；"
            f"P0 {by_priority['P0']} 条、P1 {by_priority['P1']} 条、P2 {by_priority['P2']} 条。"
        ),
        "",
        "## 怎么跑",
        "",
        "| 方式 | 命令 | 说明 |",
        "| --- | --- | --- |",
        (
            "| 接口自动（进程内） | `cd backend && .venv/bin/python -m scripts.full_function_check` | 临时 SQLite＋演示数据；"
            "OCR 工人和 AI 复核派发用替身；不连生产、不留文件 |"
        ),
        (
            "| 接口自动（打本机服务） | `.venv/bin/python -m scripts.full_function_check --base-url http://127.0.0.1:8000` | "
            "先用 launch.json 的 aicheck-demo-api 起服务；需要替身的用例会跳过 |"
        ),
        "| 只跑一部分 | `--only INSP,CONT-03` | 按模块前缀或用例编号 |",
        (
            "| 浏览器自动 | `cd frontend && pnpm exec playwright test e2e/full-function.spec.ts` | "
            "需先起演示后端（8000）并装好 Playwright 浏览器 |"
        ),
        "",
        "优先级：P0 = 主链路／安全，坏了不能发版；P1 = 常用功能；P2 = 辅助功能。",
        "",
        "## 目录",
        "",
    ]
    present = [prefix for prefix in MODULES if any(case.prefix == prefix for case in registry)]
    for index, prefix in enumerate(present, 1):
        count = sum(1 for case in registry if case.prefix == prefix)
        lines.append(f"{index}. {MODULES[prefix]}（{prefix}，{count} 条）")
    for index, prefix in enumerate(present, 1):
        lines += [
            "",
            f"## {index}. {MODULES[prefix]}（{prefix}）",
            "",
            "| 编号 | 用例 | 角色 | 优先级 | 方式 | 操作步骤 | 预期结果 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for case in (item for item in registry if item.prefix == prefix):
            steps = "<br>".join(f"{n}. {cell(step)}" for n, step in enumerate(case.steps, 1))
            role = "、".join(ROLE_LABELS.get(part, part) for part in case.role.split(","))
            lines.append(
                f"| {case.id} | {cell(case.title)} | {role} | {case.priority} | {MODE_LABELS[case.mode]} | "
                f"{steps} | {cell(case.expected)} |"
            )
    return "\n".join(lines) + "\n"


def write_catalog_csv(registry: list[Any], path: Path) -> None:
    from scripts.full_function_check.base import ROLE_LABELS

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "编号",
                "模块",
                "用例",
                "角色",
                "优先级",
                "方式",
                "操作步骤",
                "预期结果",
                "实际结果",
                "执行人",
                "日期",
            ]
        )
        for case in registry:
            role = "、".join(ROLE_LABELS.get(part, part) for part in case.role.split(","))
            steps = "\n".join(f"{n}. {step}" for n, step in enumerate(case.steps, 1))
            writer.writerow(
                [
                    case.id,
                    case.module,
                    case.title,
                    role,
                    case.priority,
                    MODE_LABELS[case.mode],
                    steps,
                    case.expected,
                    "",
                    "",
                    "",
                ]
            )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="full_function_check", description="AIcheck 全功能验收")
    parser.add_argument("--base-url", default="", help="打已在跑的服务；不给就进程内跑")
    parser.add_argument("--only", default="", help="逗号分隔的模块前缀或用例编号")
    parser.add_argument("--allow-remote", action="store_true", help="允许非本机地址（只读用例）")
    parser.add_argument(
        "--allow-writes", action="store_true", help="非本机地址也跑写用例（绝不要对生产用）"
    )
    parser.add_argument("--report-dir", default="", help="把 report.json / report.md 写到这个目录")
    parser.add_argument(
        "--catalog", default="", help="生成用例文档（.md，同目录再写一份 .csv）后退出"
    )
    parser.add_argument("--list", action="store_true", help="只列出用例编号和标题")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--keep-workdir", action="store_true", help="进程内模式保留临时目录（排查用）"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from scripts.full_function_check import load_cases
    from scripts.full_function_check.base import Context

    registry = load_cases()
    if args.catalog:
        target = Path(args.catalog)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_catalog(registry), encoding="utf-8")
        write_catalog_csv(registry, target.with_suffix(".csv"))
        print(f"已生成 {target} 和 {target.with_suffix('.csv')}（{len(registry)} 条）")
        return 0
    cases = select_cases(registry, args.only)
    if args.list:
        for case in cases:
            print(f"{case.id}\t{case.priority}\t{MODE_LABELS[case.mode]}\t{case.title}")
        return 0
    if not cases:
        print("没有选中任何用例", file=sys.stderr)
        return 2

    workdir: Path | None = None
    scratch_dirs: list[Path] = []
    if args.base_url:
        host = (urlparse(args.base_url).hostname or "").lower()
        local = host in LOCAL_HOSTS
        if not local and not args.allow_remote:
            print(
                "非本机地址默认不跑；确认是测试环境后加 --allow-remote（只跑只读用例）",
                file=sys.stderr,
            )
            return 2
        password = os.getenv("AICHECK_FULLCHECK_PASSWORD") or (demo_password() if local else "")
        if not password:
            print("请用环境变量 AICHECK_FULLCHECK_PASSWORD 提供测试账号口令", file=sys.stderr)
            return 2
        transport = http_transport(args.base_url, args.timeout)
        ctx = Context(transport, False, local or args.allow_writes, password, usernames_from_env())
        target = args.base_url
    else:
        workdir = Path(tempfile.mkdtemp(prefix="aicheck-fullcheck-"))
        logging.disable(logging.INFO)
        print(f"进程内模式，临时目录 {workdir}，正在加载应用…", flush=True)
        transport, scratch_dirs = in_process_transport(workdir)
        ctx = Context(transport, True, True, demo_password(), {role: role for role in ROLES})
        target = "进程内（临时 SQLite＋演示数据）"

    started = datetime.now().astimezone()
    try:
        results = run_cases(ctx, cases, verbose=args.verbose)
    finally:
        transport.close()
        if workdir and not args.keep_workdir:
            for path in (workdir, *scratch_dirs):
                shutil.rmtree(path, ignore_errors=True)
    counts = Counter(item["status"] for item in results)
    not_auto = sum(1 for case in cases if case.mode != "api")
    print(
        f"\n合计 {len(results)} 条接口用例：通过 {counts['PASS']}，失败 {counts['FAIL']}，"
        f"出错 {counts['ERROR']}，跳过 {counts['SKIP']}；另有 {not_auto} 条浏览器/人工用例不在本脚本里跑。"
    )
    if args.report_dir:
        meta = {
            "target": target,
            "startedAt": started.isoformat(timespec="seconds"),
            "finishedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "counts": dict(counts),
        }
        write_report(results, Path(args.report_dir), meta)
        print(f"报告已写到 {args.report_dir}")
    return 1 if counts["FAIL"] or counts["ERROR"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
