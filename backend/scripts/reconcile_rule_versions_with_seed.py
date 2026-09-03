"""把库里的业务包规则版本对齐到当前种子。

## 为什么必须有

2026-09-03 审计：生产 `rule_versions` 里 69 条 RULE-ENG-INSP-* 是 06-26 老种子
（version *-v20260703），其中 55 条的 nodeIds 与业务包 rules.yaml 错位 12 位
（R38 指向节点 50、R26 指向节点 38……）。种子只在空库时写入，业务包后来重编号，
库里的规则从没跟上；而 `current_published_rule_for_node()` 优先取库里已发布的规则，
节点 13–68 的复核就拿到了别的规则的工具计划与提示词（节点 38 跑了焊材规则）。

## 做什么

只处理 id 与种子 `RULE_VERSIONS` 同名的记录：
- 库里记录的 version/nodeIds/name/sourceRuleId 任一与种子不同 → 用种子记录整体替换
  （保留库里的 id；publishedAt/updatedAt 取种子值，revision 递增）；
- 完全一致 → 不动；
- 库里有、种子没有的（界面上另建的草稿、导入的规则）→ 不碰；
  唯一例外是 RULE-ENG-INSP-Rxx 形状、nodeIds 又不等于自己规则号的孤儿记录
  （R24/R40 被核心规则 RULE-WELDER/RULE-NDT 取代后留下的老种子）→ 置为「已下线」，
  否则它们仍是「已发布」，会和真正的规则争同一个节点。

替换前把将被改写的原记录写到 /app/output/ops/rule_versions_backup_<时间>.json，
出问题可以按 id 回写。

## 用法

    docker exec aicheck-api python3 /app/scripts/reconcile_rule_versions_with_seed.py [--apply]

不加 --apply 是 dry-run，只报告不动库。
"""

from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

sys.path.insert(0, "/app")

from libs.contracts.responses import server_time

COMPARE_FIELDS = ("version", "nodeIds", "name", "sourceRuleId", "status")


def plan_rule_version_reconciliation(
    state: dict[str, Any], seed_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """返回将被替换的 (库记录, 种子记录) 清单，不改 state。"""
    existing = {
        str(row.get("id") or ""): row
        for row in state.get("rule_versions") or []
        if isinstance(row, dict)
    }
    plan: list[dict[str, Any]] = []
    for seed in seed_rows:
        rid = str(seed.get("id") or "")
        current = existing.get(rid)
        if not current:
            continue
        diffs = {
            field: {"db": current.get(field), "seed": seed.get(field)}
            for field in COMPARE_FIELDS
            if current.get(field) != seed.get(field)
        }
        if diffs:
            plan.append({"id": rid, "current": current, "seed": seed, "diffs": diffs})
    return plan


ORPHAN_ID_PATTERN = re.compile(r"^RULE-ENG-INSP-R0*(\d+)$")


def plan_orphan_retirement(state: dict[str, Any], seed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """种子里没有、却仍「已发布」且 nodeIds 不等于自己规则号的老种子记录。"""
    seed_ids = {str(row.get("id") or "") for row in seed_rows}
    orphans: list[dict[str, Any]] = []
    for row in state.get("rule_versions") or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or "")
        match = ORPHAN_ID_PATTERN.match(rid)
        if not match or rid in seed_ids or row.get("status") != "已发布":
            continue
        node_ids = [int(item) for item in row.get("nodeIds") or [] if str(item).isdigit()]
        if node_ids == [int(match.group(1))]:
            continue
        orphans.append(row)
    return orphans


def apply_orphan_retirement(orphans: list[dict[str, Any]]) -> list[str]:
    retired: list[str] = []
    for row in orphans:
        row["retiredStatus"] = row.get("status")
        row["status"] = "已下线"
        row["retiredReason"] = "老种子孤儿记录：nodeIds 与规则号不符，且当前种子已由核心规则取代"
        row["retiredAt"] = server_time()
        row["revision"] = int(row.get("revision") or 0) + 1
        row["updatedAt"] = server_time()
        retired.append(str(row.get("id") or ""))
    return retired


def apply_rule_version_reconciliation(
    state: dict[str, Any], plan: list[dict[str, Any]]
) -> list[str]:
    rows = state.setdefault("rule_versions", [])
    replaced: list[str] = []
    for item in plan:
        rid = item["id"]
        for index, row in enumerate(rows):
            if str(row.get("id") or "") != rid:
                continue
            replacement = deepcopy(item["seed"])
            replacement["id"] = rid
            replacement["revision"] = int(row.get("revision") or 0) + 1
            replacement["updatedAt"] = server_time()
            replacement["reconciledFromVersion"] = row.get("version")
            replacement["reconciledAt"] = server_time()
            rows[index] = replacement
            replaced.append(rid)
            break
    return replaced


def main() -> int:
    from libs.db.repository import flush_state, load_state, repo
    from libs.db.seed import RULE_VERSIONS

    load_state()
    plan = plan_rule_version_reconciliation(repo.state, RULE_VERSIONS)
    print(f"[{server_time()}] 种子规则 {len(RULE_VERSIONS)} 条，库里需对齐 {len(plan)} 条")
    for item in plan:
        diffs = item["diffs"]
        print(
            f"  {item['id']}: nodeIds {diffs.get('nodeIds', {}).get('db')} -> "
            f"{diffs.get('nodeIds', {}).get('seed')} | version "
            f"{diffs.get('version', {}).get('db')} -> {diffs.get('version', {}).get('seed')}"
            + (f" | name {diffs['name']['db']} -> {diffs['name']['seed']}" if "name" in diffs else "")
        )
    orphans = plan_orphan_retirement(repo.state, RULE_VERSIONS)
    for row in orphans:
        print(f"  下线孤儿记录 {row.get('id')}: nodeIds {row.get('nodeIds')} status {row.get('status')}")
    if "--apply" not in sys.argv:
        print("（dry-run。加 --apply 才落库）")
        return 0
    if not plan and not orphans:
        print("无需变更")
        return 0
    backup_dir = Path("/app/output/ops")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = server_time().replace(" ", "T").replace(":", "")
    backup = backup_dir / f"rule_versions_backup_{stamp}.json"
    backup.write_text(
        json.dumps([item["current"] for item in plan] + [dict(row) for row in orphans], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"  原记录已备份：{backup}")
    replaced = apply_rule_version_reconciliation(repo.state, plan)
    retired = apply_orphan_retirement(orphans)
    flush_state({"rule_versions"})
    print(f"  已替换 {len(replaced)} 条：{', '.join(replaced)}")
    print(f"  已下线孤儿 {len(retired)} 条：{', '.join(retired)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
