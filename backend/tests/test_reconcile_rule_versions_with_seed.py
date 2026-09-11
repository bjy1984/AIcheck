"""库里的规则版本要能对齐到当前种子（2026-09-03 生产错位 12 位的事故）。

判据：
- 与种子 nodeIds/version/name 不一致的同 id 记录被种子记录替换，id 保留、revision 递增；
- 完全一致的不动；
- 库里独有的（界面另建的草稿）不碰；
- 种子本身：每条 RULE-ENG-INSP-Rxx 的 nodeIds 都等于其规则号，
  这是错位事故的直接回归断言。
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
from copy import deepcopy

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reconcile_rule_versions_with_seed.py"


def _load_module():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("reconcile_rule_versions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _seed_rows():
    from libs.db.seed import RULE_VERSIONS

    return deepcopy(RULE_VERSIONS)


def test_种子里规则号与节点号一致():
    for row in _seed_rows():
        match = re.fullmatch(r"RULE-ENG-INSP-R(\d+)", str(row.get("id") or ""))
        if not match:
            continue
        assert row.get("nodeIds") == [int(match.group(1))], row.get("id")


def test_错位记录被替换_一致与独有记录不动():
    module = _load_module()
    seed = _seed_rows()
    r38 = next(row for row in seed if row["id"] == "RULE-ENG-INSP-R38")
    r01 = next(row for row in seed if row["id"] == "RULE-ENG-INSP-R01")
    stale_r38 = {
        **deepcopy(r38),
        "version": "engineering-inspection-r38-v20260703",
        "nodeIds": [50],
        "name": "套管防腐绝缘",
        "revision": 3,
    }
    draft = {"id": "RULE-DRAFT-X", "status": "草稿", "nodeIds": [5], "version": "x"}
    state = {"rule_versions": [stale_r38, deepcopy(r01), draft]}

    plan = module.plan_rule_version_reconciliation(state, seed)
    assert [item["id"] for item in plan] == ["RULE-ENG-INSP-R38"]
    assert plan[0]["diffs"]["nodeIds"] == {"db": [50], "seed": [38]}

    replaced = module.apply_rule_version_reconciliation(state, plan)
    assert replaced == ["RULE-ENG-INSP-R38"]
    fixed = next(row for row in state["rule_versions"] if row["id"] == "RULE-ENG-INSP-R38")
    assert fixed["nodeIds"] == [38]
    assert fixed["version"] == r38["version"]
    assert fixed["revision"] == 4
    assert fixed["reconciledFromVersion"] == "engineering-inspection-r38-v20260703"
    assert next(row for row in state["rule_versions"] if row["id"] == "RULE-DRAFT-X") is draft
    assert next(row for row in state["rule_versions"] if row["id"] == "RULE-ENG-INSP-R01") == r01


def test_种子没有的错位孤儿记录被下线_对齐的不动():
    module = _load_module()
    seed = _seed_rows()
    orphan = {"id": "RULE-ENG-INSP-R24", "status": "已发布", "nodeIds": [36], "version": "old", "revision": 1}
    aligned_extra = {"id": "RULE-ENG-INSP-R99", "status": "已发布", "nodeIds": [99], "version": "x"}
    draft = {"id": "RULE-ENG-INSP-R40", "status": "草稿", "nodeIds": [52], "version": "y"}
    state = {"rule_versions": [orphan, aligned_extra, draft]}
    orphans = module.plan_orphan_retirement(state, seed)
    assert [row["id"] for row in orphans] == ["RULE-ENG-INSP-R24"]
    assert module.apply_orphan_retirement(orphans) == ["RULE-ENG-INSP-R24"]
    assert orphan["status"] == "已下线" and orphan["retiredStatus"] == "已发布" and orphan["revision"] == 2


def test_种子里有库里整条缺失的规则被补写():
    """2026-09-11 生产：库里根本没有 RULE-ENG-INSP-R28，节点 28（管道组对）
    于是落到老种子焊工资格证规则上。对齐脚本原来对缺失记录直接 continue。"""
    module = _load_module()
    seed = _seed_rows()
    r28 = next(row for row in seed if row["id"] == "RULE-ENG-INSP-R28")
    keep = next(row for row in seed if row["id"] == "RULE-ENG-INSP-R29")
    draft = {"id": "RULE-DRAFT-X", "status": "草稿", "nodeIds": [5], "version": "x"}
    state = {"rule_versions": [deepcopy(keep), draft]}

    missing = module.plan_missing_rule_versions(state, seed)
    assert "RULE-ENG-INSP-R28" in [row["id"] for row in missing]
    assert "RULE-ENG-INSP-R29" not in [row["id"] for row in missing]

    inserted = module.apply_missing_rule_versions(state, missing)
    assert "RULE-ENG-INSP-R28" in inserted
    written = next(row for row in state["rule_versions"] if row["id"] == "RULE-ENG-INSP-R28")
    assert written["nodeIds"] == [28]
    assert written["version"] == r28["version"]
    assert written["reconciledAt"] and written["reconciledFromVersion"] is None
    assert next(row for row in state["rule_versions"] if row["id"] == "RULE-DRAFT-X") is draft
    assert module.plan_missing_rule_versions(state, seed) == []


def test_种子里没有两条已发布规则抢同一个节点():
    """RULE-WELDER-202606 曾声明 nodeIds [24, 25, 27, 28]，与 R25/R27
    的 publishedAt 完全相同——选谁只看列表顺序。节点到规则必须是唯一的。"""
    from collections import defaultdict

    published = defaultdict(list)
    for row in _seed_rows():
        if row.get("status") != "已发布":
            continue
        for node in row.get("nodeIds") or []:
            published[int(node)].append(str(row.get("id")))
    contested = {node: ids for node, ids in published.items() if len(ids) > 1}
    assert not contested, contested
