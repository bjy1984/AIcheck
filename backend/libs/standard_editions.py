"""标准换版对照：哪些被引用的标准已经出了新版。

## 为什么要有

规则里的「标准规范」是随业务包固化的：节点 24/29 写的是 TSG Z6002-2010，节点 25 写的是
NB/T 47014-2023。前者已被 **TSG Z6002-2026**（2026-08-01 施行）取代——2026-09-13 把条款
原文显示到界面上之后，监检人员会照着一份过期规范去核对，比不显示更糟。

## 口径

- 只登记**核实过原文施行日期**的换版（见 `docs/研究-焊接材料设计节点审查原则.md` 第 1、2 章
  与 `docs/lab/verification/2026-09-11-welder-tsg-z6002-2026.md`）。没核实的宁可不写。
- 只做提示，不改判定：判定用哪版是规则版本的事，这里只负责让人看见「你引的是旧版」。
- `effectiveFrom` 是新版施行日；在那之前引旧版是对的，所以按业务日期判断是否提示。
"""
from __future__ import annotations

import re
from typing import Any

from libs.contracts.responses import business_today

#: 旧版标准号 → 新版信息。键按「去空格、去下划线、大写」归一后匹配。
SUPERSEDED_EDITIONS: dict[str, dict[str, str]] = {
    "TSGZ6002-2010": {
        "supersededBy": "TSG Z6002-2026",
        "effectiveFrom": "2026-08-01",
        "note": "焊工考核细则换版：FeⅠ/Ⅱ/Ⅲ 互认、FeⅣ 独立，GMAW/FCAW 拆分，6G 不覆盖向下焊。",
    },
    "TSGD0001-2009": {
        "supersededBy": "TSG 31-2025",
        "effectiveFrom": "2026-01-01",
        "note": "压力管道安全技术规程换版：分级改为 GC1/GC2/GCD（无 GC3），DN≥50。",
    },
    "NB/T47014-2011": {
        "supersededBy": "NB/T 47014-2023",
        "effectiveFrom": "2023-12-01",
        "note": "焊接工艺评定换版：预热阈值 55℃，SMAW 极性升为重要因素。",
    },
    "GB/T20801.1-2020": {
        "supersededBy": "GB/T 20801.1-2025",
        "effectiveFrom": "2026-05-01",
        "note": "压力管道规范 2025 版自 2026-05-01 合并取代 2020 版六部分。",
    },
    "GB/T1591-2008": {
        "supersededBy": "GB/T 1591-2018",
        "effectiveFrom": "2019-02-01",
        "note": "低合金高强度结构钢换版：Q345 已由 Q355 取代。",
    },
}


def _normalize(reference: str) -> str:
    return re.sub(r"[\s_]", "", str(reference or "")).upper().replace("—", "-").replace("－", "-")


def superseded_edition(reference: str, *, on: str | None = None) -> dict[str, Any] | None:
    """这条标准引用是否已被新版取代；没被取代（或新版还没施行）返回 None。

    `on` 是判断基准日（默认业务当天）：新版施行前引旧版是对的，不该提示。
    """
    entry = SUPERSEDED_EDITIONS.get(_normalize(reference))
    if not entry:
        return None
    reference_date = str(on or business_today())
    if reference_date < entry["effectiveFrom"]:
        return None
    return {"reference": reference, **entry}
