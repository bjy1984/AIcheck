"""把生产库资料审查点的 id 重键到配置文件的 id，并同步改写所有引用（2.4 存量迁移前置）。

2026-09-06 核实：生产 admin_config.materialReviewPoints 164 条，只有 18 条 id 与
config/material_review_points.json 一致。id 的哈希后缀由映射表行序与内容生成，老种子的行序早已
不同，于是按 id 的 reconcile 从未触达其余 146 条——映射表的任何改动都到不了生产。

做法：按 (nodeId, materialTypeCode) 唯一匹配得到 旧 id → 新 id；改写
  - admin_config.materialReviewPoints[].id（旧 id 记进 previousIds）
  - node_evidence_links[].reviewPointId
  - bindings[].reviewPointIds / requirementId（只改 MRP- 前缀的）
  - rectifications[].supplementRequirements[].id（只改 MRP- 前缀的）
匹配不唯一或无匹配的一律不动，列在 unmatched 里供人工核对。历史 AiRun 里的证据链接副本是快照，不动。

默认 dry-run，只打印变更清单；--apply 才写库。可通过 ssh 管道直接执行（不依赖 __file__）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1] if "__file__" in globals() else Path("/app")
sys.path.insert(0, str(BACKEND_ROOT))

from libs.db.repository import flush_state, load_state, repo

REFERENCE_PREFIX = "MRP-"


def build_id_mapping(
    points: list[dict[str, Any]], asset_items: list[dict[str, Any]], business_pack_id: str
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """返回 (旧 id → 新 id, 未匹配清单)。已一致的 id 不进映射。"""
    asset_ids = {str(item.get("id")) for item in asset_items if isinstance(item, dict) and item.get("id")}
    by_key: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for item in asset_items:
        if isinstance(item, dict):
            by_key.setdefault((int(item.get("nodeId") or 0), str(item.get("materialTypeCode") or "")), []).append(item)
    mapping: dict[str, str] = {}
    unmatched: list[dict[str, Any]] = []
    taken: set[str] = set()
    for point in points:
        if not isinstance(point, dict) or not point.get("id"):
            continue
        if str(point.get("businessPackId") or business_pack_id) != business_pack_id:
            continue
        old_id = str(point["id"])
        if old_id in asset_ids:
            continue
        candidates = by_key.get((int(point.get("nodeId") or 0), str(point.get("materialTypeCode") or "")), [])
        if len(candidates) != 1 or str(candidates[0]["id"]) in taken:
            unmatched.append(
                {"id": old_id, "nodeId": point.get("nodeId"), "materialTypeCode": point.get("materialTypeCode"), "candidates": [str(c.get("id")) for c in candidates]}
            )
            continue
        new_id = str(candidates[0]["id"])
        mapping[old_id] = new_id
        taken.add(new_id)
    return mapping, unmatched


def rewrite_references(state: dict[str, Any], mapping: dict[str, str]) -> dict[str, int]:
    """按映射改写所有引用；返回每个集合改了多少条。只在内存里改，落库由调用方决定。"""
    counts = {"materialReviewPoints": 0, "node_evidence_links": 0, "bindings": 0, "rectifications": 0}
    for point in state.get("admin_config", {}).get("materialReviewPoints", []) or []:
        old_id = str(point.get("id") or "")
        if old_id in mapping:
            point["id"] = mapping[old_id]
            previous = [str(item) for item in point.get("previousIds") or []]
            point["previousIds"] = [*previous, old_id] if old_id not in previous else previous
            counts["materialReviewPoints"] += 1
    for link in state.get("node_evidence_links", []) or []:
        if isinstance(link, dict) and str(link.get("reviewPointId") or "") in mapping:
            link["reviewPointId"] = mapping[str(link["reviewPointId"])]
            counts["node_evidence_links"] += 1
    for binding in state.get("bindings", []) or []:
        if not isinstance(binding, dict):
            continue
        changed = False
        ids = binding.get("reviewPointIds")
        if isinstance(ids, list) and any(str(item) in mapping for item in ids):
            binding["reviewPointIds"] = [mapping.get(str(item), item) for item in ids]
            changed = True
        requirement_id = str(binding.get("requirementId") or "")
        if requirement_id.startswith(REFERENCE_PREFIX) and requirement_id in mapping:
            binding["requirementId"] = mapping[requirement_id]
            changed = True
        counts["bindings"] += int(changed)
    for rectification in state.get("rectifications", []) or []:
        if not isinstance(rectification, dict):
            continue
        changed = False
        for requirement in rectification.get("supplementRequirements") or []:
            if isinstance(requirement, dict) and str(requirement.get("id") or "") in mapping:
                requirement["id"] = mapping[str(requirement["id"])]
                changed = True
        counts["rectifications"] += int(changed)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--asset", default=str(BACKEND_ROOT / "config" / "material_review_points.json"))
    parser.add_argument("--business-pack", default="engineering_inspection_v1")
    parser.add_argument("--apply", action="store_true", help="真正写库；默认只打印映射与变更计数")
    args = parser.parse_args()

    payload = json.loads(Path(args.asset).read_text(encoding="utf-8"))
    if payload.get("businessPackId") != args.business_pack:
        print(f"asset businessPackId={payload.get('businessPackId')} 与 --business-pack 不一致", file=sys.stderr)
        return 2
    load_state()
    points = repo.state.setdefault("admin_config", {}).setdefault("materialReviewPoints", [])
    mapping, unmatched = build_id_mapping(points, payload.get("items") or [], args.business_pack)
    report: dict[str, Any] = {"apply": args.apply, "mappingCount": len(mapping), "unmatched": unmatched}
    if args.apply:
        report["rewritten"] = rewrite_references(repo.state, mapping)
    else:
        # dry-run 也算一遍改写计数，但算在副本上
        import copy

        preview = {
            "admin_config": {"materialReviewPoints": copy.deepcopy(points)},
            "node_evidence_links": copy.deepcopy(repo.state.get("node_evidence_links", [])),
            "bindings": copy.deepcopy(repo.state.get("bindings", [])),
            "rectifications": copy.deepcopy(repo.state.get("rectifications", [])),
        }
        report["wouldRewrite"] = rewrite_references(preview, mapping)
    report["mapping"] = mapping
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.apply and mapping:
        flush_state({"node_evidence_links", "bindings", "rectifications"}, selected_singleton_keys={"admin_config"})
        print("flushed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
