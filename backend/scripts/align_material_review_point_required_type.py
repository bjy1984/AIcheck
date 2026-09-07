"""把生产库 admin_config.materialReviewPoints 的 requiredType 对齐到配置文件（按 id 显式指定）。

背景：`repository.reconcile_material_review_points` 只对齐派生字段（类别、模块、类型码、审查类），
**不碰 requiredType**——它在管理台可编辑，自动对齐会把管理员的手工调整抹掉。所以映射表里把
一份资料从"必传"改成"可选"之后，生产库的旧审查点仍然是必传，节点 readiness 照旧要它。

2026-09-06 第一次用途：N-34 焊工名册（MRP-24-welder_roster-08506E）从必传降为可选——
名册由施工方自填，与证书、平台记录不一致时以证书和平台为准，缺名册不该算缺材料。

默认 dry-run：列出配置文件与库里 requiredType 不一致的全部审查点。
真正写库要同时给 --apply 和 --ids（显式说清改哪几条），不提供"全部对齐"——那等于把
requiredType 变成派生字段。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from libs.db.repository import load_state, repo


def required_type_drift(
    points: list[dict[str, Any]], asset_items: list[dict[str, Any]], business_pack_id: str
) -> list[dict[str, Any]]:
    expected = {
        str(item.get("id")): item
        for item in asset_items
        if isinstance(item, dict) and item.get("id")
    }
    drift: list[dict[str, Any]] = []
    for index, item in enumerate(points):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        if str(item.get("businessPackId") or business_pack_id) != business_pack_id:
            continue
        source = expected.get(str(item["id"]))
        if not source:
            continue
        current = str(item.get("requiredType") or "")
        target = str(source.get("requiredType") or "")
        if current != target:
            drift.append(
                {
                    "id": str(item["id"]),
                    # 按位置写回：同一 id 可能在另一个业务包下也有一条，不能按 id 查最后一个
                    "index": index,
                    "nodeId": item.get("nodeId"),
                    "materialTypeCode": item.get("materialTypeCode"),
                    "current": current,
                    "target": target,
                }
            )
    return drift


def apply_alignment(points: list[dict[str, Any]], drift: list[dict[str, Any]], ids: set[str]) -> list[str]:
    applied: list[str] = []
    for change in drift:
        if change["id"] not in ids:
            continue
        index = int(change.get("index", -1))
        item = points[index] if 0 <= index < len(points) else None
        if not isinstance(item, dict) or str(item.get("id")) != change["id"]:
            continue
        item["requiredType"] = change["target"]
        item["requiredTypeAlignedFrom"] = change["current"]
        applied.append(change["id"])
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--asset", default=str(BACKEND_ROOT / "config" / "material_review_points.json"))
    parser.add_argument("--business-pack", default="engineering_inspection_v1")
    parser.add_argument("--ids", default="", help="逗号分隔的审查点 id；--apply 时必填")
    parser.add_argument("--apply", action="store_true", help="真正写库；默认只打印不一致清单")
    args = parser.parse_args()

    payload = json.loads(Path(args.asset).read_text(encoding="utf-8"))
    if payload.get("businessPackId") != args.business_pack:
        print(f"asset businessPackId={payload.get('businessPackId')} 与 --business-pack 不一致", file=sys.stderr)
        return 2

    load_state()
    points = repo.state.setdefault("admin_config", {}).setdefault("materialReviewPoints", [])
    drift = required_type_drift(points, payload.get("items") or [], args.business_pack)
    applied: list[str] = []
    if args.apply:
        ids = {item.strip() for item in args.ids.split(",") if item.strip()}
        if not ids:
            print("--apply 必须配合 --ids 显式指定要对齐的审查点", file=sys.stderr)
            return 2
        unknown = sorted(ids - {change["id"] for change in drift})
        if unknown:
            print(f"以下 id 不在不一致清单里（已一致或不存在）：{unknown}", file=sys.stderr)
        applied = apply_alignment(points, drift, ids)
    print(json.dumps({"apply": args.apply, "drift": drift, "applied": applied}, ensure_ascii=False, indent=2))
    if applied:
        repo.flush()
        print("flushed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
