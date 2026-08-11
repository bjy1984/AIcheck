"""对比 FastAPI 实际注册的路由与手工维护的 OpenAPI 契约（issue #10 / A-4）。

手工契约只声明了 24 个路径，而 routes.py 实际注册 300+ 个；前后端对齐完全依赖
人工与 20 万字 Markdown，无法机器校验。契约测试测的是行为快照，发现不了
「文档说 A、实现是 B」。

这个脚本把「实现」当唯一真源导出，并给出可在 CI 里盯住的覆盖率：

    python -m scripts.openapi_route_coverage                 # 打印覆盖率摘要
    python -m scripts.openapi_route_coverage --json          # 机器可读
    python -m scripts.openapi_route_coverage --export out.json   # 导出实现侧全量契约
    python -m scripts.openapi_route_coverage --min-coverage 8    # 覆盖率低于阈值即失败

阈值是「不许再退」的棘轮，不是「已经够好」的标记——手工契约每补一条就把它往上调。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
# 这些不是业务契约的一部分：健康探针、文档页、内部兼容 mock。
EXCLUDED_PATH_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/mock/")


def implemented_operations() -> dict[str, set[str]]:
    """FastAPI 生成的 OpenAPI 里的 {路径: {方法}}——实现即真源。

    注意不能用 app.routes：业务路由挂在子 router 上，app.routes 只有十来条。
    同一个 router 被挂了 /api 与无前缀两份，normalize() 会把它们合并。
    """
    from apps.api.main import app

    operations: dict[str, set[str]] = {}
    for path, item in (app.openapi().get("paths") or {}).items():
        if path.startswith(EXCLUDED_PATH_PREFIXES):
            continue
        methods = {key.lower() for key in item if key.lower() in HTTP_METHODS}
        if methods:
            operations.setdefault(path, set()).update(methods)
    return operations


def documented_operations() -> dict[str, set[str]]:
    """手工 OpenAPI 契约声明的 {路径: {方法}}。"""
    from scripts.openapi_contract import build_contract_index

    index = build_contract_index()
    operations: dict[str, set[str]] = {}
    for entry in index.get("operations") or []:
        path = str(entry.get("path") or "")
        method = str(entry.get("method") or "").lower()
        if path and method in HTTP_METHODS:
            operations.setdefault(path, set()).add(method)
    return operations


def normalize(path: str) -> str:
    """抹平两处纯书写差异，只比较真实的路径结构。

    1. 前缀：同一个 router 被挂了 /api 与无前缀两份；
    2. 路径参数命名：契约写 {projectId}，实现（FastAPI 函数签名）写 {project_id}。
       两者指的是同一个位置参数，名字不同不构成契约差异。
    """
    without_prefix = path[4:] if path.startswith("/api/") else path
    return re.sub(r"\{[^}]+\}", "{}", without_prefix)


def coverage_report() -> dict[str, Any]:
    implemented = implemented_operations()
    documented = documented_operations()

    implemented_pairs = {
        (normalize(path), method) for path, methods in implemented.items() for method in methods
    }
    documented_pairs = {
        (normalize(path), method) for path, methods in documented.items() for method in methods
    }

    covered = sorted(implemented_pairs & documented_pairs)
    undocumented = sorted(implemented_pairs - documented_pairs)
    # 契约里有、实现里没有——这是真正的「文档说 A、实现没有 A」，比未覆盖更严重。
    stale = sorted(documented_pairs - implemented_pairs)

    total = len(implemented_pairs)
    return {
        "implementedOperationCount": total,
        "documentedOperationCount": len(documented_pairs),
        "coveredOperationCount": len(covered),
        "coveragePercent": round(len(covered) / total * 100, 1) if total else 0.0,
        "staleContractOperations": [f"{method.upper()} {path}" for path, method in stale],
        "undocumentedOperations": [f"{method.upper()} {path}" for path, method in undocumented],
    }


def export_document(target: Path) -> dict[str, Any]:
    """导出实现侧的完整 OpenAPI，作为对齐用的机器可读真源。"""
    from apps.api.main import app

    document = app.openapi()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="以 JSON 输出报告")
    parser.add_argument("--export", type=Path, help="把实现侧 OpenAPI 导出到该路径")
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=None,
        help="覆盖率低于该百分比时退出码非 0（CI 棘轮）",
    )
    args = parser.parse_args()

    report = coverage_report()
    if args.export:
        document = export_document(args.export)
        report["exportedPath"] = str(args.export)
        report["exportedPathCount"] = len(document.get("paths") or {})

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"实现侧操作数：{report['implementedOperationCount']}")
        print(f"契约声明操作数：{report['documentedOperationCount']}")
        print(f"已覆盖：{report['coveredOperationCount']}（{report['coveragePercent']}%）")
        if report["staleContractOperations"]:
            print(f"\n契约有、实现没有（{len(report['staleContractOperations'])} 条，应优先清理）：")
            for item in report["staleContractOperations"][:20]:
                print(f"  {item}")
        print(f"\n未纳入契约：{len(report['undocumentedOperations'])} 条")
        for item in report["undocumentedOperations"][:15]:
            print(f"  {item}")
        if len(report["undocumentedOperations"]) > 15:
            print(f"  …… 其余 {len(report['undocumentedOperations']) - 15} 条")

    if report["staleContractOperations"]:
        print("\n契约里存在实现侧没有的操作——这是「文档说 A、实现是 B」，必须修。", file=sys.stderr)
        return 2
    if args.min_coverage is not None and report["coveragePercent"] < args.min_coverage:
        print(
            f"\n覆盖率 {report['coveragePercent']}% 低于阈值 {args.min_coverage}%。",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
