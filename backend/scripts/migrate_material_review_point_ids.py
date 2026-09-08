"""审查点 ID 迁移：先匹配节点/类型，再用内容消歧；歧义、冲突、孤儿阻止整次写入。

只读取四个持久化集合，不调用会补种数据的 repository.load_state。
默认只读事务；正式写入要求维护窗口、精确旧 ID 清单及 dry-run 摘要一致。
证据链接、资料挂载及整改要求同步改写，历史 AI 快照保持原样。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1] if "__file__" in globals() else Path("/app")
sys.path.insert(0, str(BACKEND_ROOT))

from libs.security.tenant import current_tenant_id

COLLECTIONS = {"node_evidence_links": "node_evidence_links", "bindings": "node_bindings", "rectifications": "rectifications"}

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
    taken: set[str] = {str(point.get("id")) for point in points if isinstance(point, dict)}
    for point in points:
        if not isinstance(point, dict) or not point.get("id"):
            continue
        if str(point.get("businessPackId") or business_pack_id) != business_pack_id:
            continue
        old_id = str(point["id"])
        if old_id in asset_ids:
            continue
        candidates = by_key.get((int(point.get("nodeId") or 0), str(point.get("materialTypeCode") or "")), [])
        if len(candidates) > 1:
            # Legacy R01 has two design_document points with the same reviewContent;
            # the documented file content distinguishes seal identity from scope.
            for field in ("reviewContent", "fileContent"):
                value = str(point.get(field) or "").strip()
                narrowed = [item for item in candidates if value and str(item.get(field) or "").strip() == value]
                if len(narrowed) == 1:
                    candidates = narrowed
                    break
        if len(candidates) != 1 or str(candidates[0]["id"]) in taken:
            unmatched.append(
                {"id": old_id, "enabled": point.get("enabled"), "nodeId": point.get("nodeId"), "materialTypeCode": point.get("materialTypeCode"), "candidates": [str(c.get("id")) for c in candidates]}
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


def reference_ids(state: dict[str, Any]) -> list[tuple[str, str, str]]:
    references = []
    for collection in ("node_evidence_links", "bindings", "rectifications"):
        for record in state.get(collection, []) or []:
            ids = []
            if collection == "node_evidence_links":
                ids = [record.get("reviewPointId")]
            elif collection == "bindings":
                ids = [*(record.get("reviewPointIds") or []), record.get("requirementId")]
            else:
                ids = [item.get("id") for item in record.get("supplementRequirements") or []]
            references.extend((collection, str(record.get("id") or ""), str(value))
                              for value in ids if str(value or "").startswith(REFERENCE_PREFIX))
    return references


def build_migration_plan(state: dict[str, Any], asset: dict[str, Any], business_pack_id: str,
                         excluded_inactive_ids: set[str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    points = state.get("admin_config", {}).get("materialReviewPoints", []) or []
    items = asset.get("items") or []
    errors = []
    if asset.get("businessPackId") != business_pack_id:
        errors.append("asset_business_pack_mismatch")
    for label, rows in (("state", points), ("asset", items)):
        ids = [str(item.get("id") or "") for item in rows]
        if any(not value for value in ids) or len(ids) != len(set(ids)):
            errors.append(f"{label}_duplicate_or_empty_ids")
    mapping, unmatched = build_id_mapping(points, items, business_pack_id)
    refs = reference_ids(state)
    referenced = {value for _, _, value in refs}
    excluded = []
    approved = excluded_inactive_ids or set()
    point_by_id = {str(item.get("id")): item for item in points}
    for value in approved:
        point = point_by_id.get(value) or {}
        if point.get("enabled") is not False or value in referenced:
            errors.append(f"invalid_inactive_exclusion:{value}")
        else:
            excluded.append({"id": value, "reason": "disabled_without_live_references"})
            mapping.pop(value, None)
    blocking = [item for item in unmatched if item["id"] not in {item["id"] for item in excluded}]
    errors.extend(f"unmatched:{item['id']}" for item in blocking)
    preview = copy.deepcopy(state)
    counts = rewrite_references(preview, mapping)
    resulting_ids = {str(item.get("id")) for item in preview.get("admin_config", {}).get("materialReviewPoints", [])}
    orphans = [{"collection": collection, "recordId": record, "reviewPointId": value}
               for collection, record, value in reference_ids(preview) if value not in resulting_ids]
    if orphans:
        errors.append("orphan_references")
    snapshot = {key: state.get(key) for key in ("admin_config", "node_evidence_links", "bindings", "rectifications")}
    digest = hashlib.sha256(json.dumps({"state": snapshot, "asset": asset, "excluded": sorted(approved)},
                                     sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    report = {"apply": False, "safeToApply": not errors, "mappingCount": len(mapping), "mapping": mapping,
              "unmatched": unmatched, "excluded": excluded, "errors": errors, "orphanReferences": orphans,
              "wouldRewrite": counts, "planSha256": digest}
    return report, preview


@contextmanager
def persistent_snapshot(*, apply: bool):
    """No schema creation, seeding, reconcile, or credentials in output."""
    import psycopg

    dsn = os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        raise ValueError("A PostgreSQL connection is required; use --state for offline dry-run")
    with psycopg.connect(dsn) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" + ("" if apply else " READ ONLY"))
        if apply:
            # Prevent new references as well as changes to the approved snapshot.
            connection.execute("SET LOCAL lock_timeout = '10s'")
            connection.execute("LOCK TABLE aicheck_state, aicheck_singletons IN SHARE ROW EXCLUSIVE MODE")
        tenant = current_tenant_id()
        row = connection.execute("SELECT payload FROM aicheck_singletons WHERE tenant_id = %s AND name = 'admin_config'", (tenant,)).fetchone()
        if not row:
            raise ValueError("Persisted admin_config missing; refusing seed fallback")
        state = {"admin_config": row[0]}
        for key, collection in COLLECTIONS.items():
            rows = connection.execute("SELECT object_id, payload FROM aicheck_state WHERE tenant_id = %s AND collection = %s ORDER BY object_id", (tenant, collection)).fetchall()
            state[key] = [payload for _, payload in rows]
            if any(str(payload.get("id")) != str(object_id) for object_id, payload in rows):
                raise ValueError(f"Object ID mismatch in {collection}")
        yield state, connection


def persist_preview(connection, original: dict[str, Any], preview: dict[str, Any]) -> None:
    tenant = current_tenant_id()
    if original["admin_config"] != preview["admin_config"]:
        connection.execute("UPDATE aicheck_singletons SET payload = %s::jsonb, updated_at = now() WHERE tenant_id = %s AND name = 'admin_config'", (json.dumps(preview["admin_config"], ensure_ascii=False), tenant))
    for key, collection in COLLECTIONS.items():
        for before, after in zip(original[key], preview[key], strict=True):
            if before != after:
                connection.execute("UPDATE aicheck_state SET payload = %s::jsonb, updated_at = now() WHERE tenant_id = %s AND collection = %s AND object_id = %s", (json.dumps(after, ensure_ascii=False), tenant, collection, before["id"]))


def process_snapshot(args, payload, state, connection=None) -> int:
    exclusions = set(args.exclude_inactive_id)
    if args.check_current:
        referenced = {value for _, _, value in reference_ids(state)}
        exclusions.update(str(p["id"]) for p in state["admin_config"].get("materialReviewPoints", []) if p.get("enabled") is False and str(p["id"]) not in referenced)
    report, preview = build_migration_plan(state, payload, args.business_pack, exclusions)
    if args.apply and (set(args.ids) != set(report["mapping"]) or args.expect_plan_sha256 != report["planSha256"]):
        report["errors"].append("approved_plan_or_ids_changed")
        report["safeToApply"] = False
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["safeToApply"]:
        return 2
    if args.check_current and report["mapping"]:
        return 3
    if args.apply and report["mapping"]:
        persist_preview(connection, state, preview)
        print("Migration written in transaction; commit occurs on successful exit")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--asset", default=str(BACKEND_ROOT / "config" / "material_review_points.json"))
    parser.add_argument("--business-pack", default="engineering_inspection_v1")
    parser.add_argument("--state", type=Path, help="Offline snapshot for dry-run; never written")
    parser.add_argument("--exclude-inactive-id", action="append", default=[])
    parser.add_argument("--ids", nargs="+", help="Exact old IDs approved by the dry-run")
    parser.add_argument("--expect-plan-sha256", help="Dry-run digest; reject changed state or asset")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--maintenance-confirmed", action="store_true", help="Writers stopped, in-flight work drained, server backup verified")
    parser.add_argument("--check-current", action="store_true", help="Deployment gate: nonzero if migration is needed")
    args = parser.parse_args()
    if args.apply and (args.state or args.check_current or not args.ids or not args.expect_plan_sha256 or not args.maintenance_confirmed):
        parser.error("--apply requires --ids, --expect-plan-sha256 and --maintenance-confirmed; no --state/--check-current")
    payload = json.loads(Path(args.asset).read_text(encoding="utf-8"))
    if args.state:
        return process_snapshot(args, payload, json.loads(args.state.read_text(encoding="utf-8")))
    with persistent_snapshot(apply=args.apply) as (state, connection):
        return process_snapshot(args, payload, state, connection)


if __name__ == "__main__":
    raise SystemExit(main())
