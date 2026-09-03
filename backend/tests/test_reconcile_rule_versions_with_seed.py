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
