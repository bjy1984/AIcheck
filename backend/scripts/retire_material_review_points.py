"""把生产库 admin_config.materialReviewPoints 里已从配置文件移除的审查点置为 enabled=False。

背景：`repository.reconcile_material_review_points` 只对齐派生字段、不删除库里多出的条目
（对齐不该变成清空）。所以从 docs/工程监检资料映射表.md 删掉一行、重新生成
config/material_review_points.json 之后，**生产库里的旧审查点仍然 enabled=True**，
节点 readiness 会继续要求那份资料。

2026-09-06 第一次用途：节点 9（设计文件上注明的无损检测、防腐、耐压试验和泄漏试验要求）
错配了 leakage_test_report 与 instrument_calibration_certificate 两份试验类资料，
让存量项目的节点 9 长期"缺材料"。

只置 enabled=False，不删除：证据链上引用了这些 reviewPointId 的记录仍能解析。
默认 dry-run；带 --apply 才写库。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from libs.db.repository import load_state, repo  # noqa: E402


def retired_ids_from_asset(asset_path: Path, current_ids: set[str], business_pack_id: str) -> list[str]:
    payload = json.loads(asset_path.read_text(encoding="utf-8"))
    if payload.get("businessPackId") != business_pack_id:
        return []
    asset_ids = {str(item.get("id")) for item in payload.get("items") or [] if item.get("id")}
    return sorted(current_ids - asset_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ids", default="", help="逗号分隔的审查点 id；留空则按配置文件差集自动计算")
    parser.add_argument("--asset", default=str(BACKEND_ROOT / "config" / "material_review_points.json"))
    parser.add_argument("--business-pack", default="engineering_inspection_v1")
    parser.add_argument("--apply", action="store_true", help="真正写库；默认只打印")
    args = parser.parse_args()

    load_state()
    points = repo.state.setdefault("admin_config", {}).setdefault("materialReviewPoints", [])
    by_id = {str(item.get("id")): item for item in points if isinstance(item, dict) and item.get("id")}
    if args.ids.strip():
        targets = [item.strip() for item in args.ids.split(",") if item.strip()]
    else:
        pack_ids = {
            pid
            for pid, item in by_id.items()
            if str(item.get("businessPackId") or args.business_pack) == args.business_pack
        }
        targets = retired_ids_from_asset(Path(args.asset), pack_ids, args.business_pack)

    changes: list[dict[str, object]] = []
    for target in targets:
        item = by_id.get(target)
        if item is None:
            changes.append({"id": target, "action": "missing_in_state"})
            continue
        if item.get("enabled", True) is False:
            changes.append({"id": target, "action": "already_disabled"})
            continue
        changes.append(
            {
                "id": target,
                "action": "disable",
                "nodeId": item.get("nodeId"),
                "materialTypeCode": item.get("materialTypeCode"),
                "requiredType": item.get("requiredType"),
            }
        )
        if args.apply:
            item["enabled"] = False
            item["retiredReason"] = "removed_from_mapping_doc"

    print(json.dumps({"apply": args.apply, "targets": targets, "changes": changes}, ensure_ascii=False, indent=2))
    if args.apply and any(change["action"] == "disable" for change in changes):
        repo.flush()
        print("flushed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
