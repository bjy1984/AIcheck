"""施工記錄的適用性：按管線號到設計管線事實裡找依據，只宣告「適用」，不宣告「不適用」。

2026-09-24 業務確認的口徑：
- R66／R67 泄漏試驗：設計表的泄漏試驗要求打 √，或介質有毒／有泄漏危害性（設計資料明寫）即適用；
- R47 靜電接地：介質火災危險性為甲、乙類，或設計表寫明介質特性可燃／易燃即適用；
- 判不了就維持「適用性未知 → 證據不足」，不按不適用放過；介質名稱本身不拿來猜。
設計文件寫明靜電接地要求這一路，要等設計事實能交接到這些節點再接。
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from libs.regulatory_tables import medium_hazard_flags

_FIRE_CLASS_RE = re.compile(r"^[甲乙](?:[AaBb]|类|類)?$|可燃|易燃")


def _key(value: Any) -> str:
    return re.sub(r"[\s\-－_]", "", str(value or "")).upper()


_DN_RE = re.compile(r"^\s*(?:DN)?\s*(\d{2,4})\s*$", re.IGNORECASE)
_DN_SUFFIX_RE = re.compile(r"^(?P<line>.+?)[-－_](?P<dn>\d{2,4})$")


def _matching_pipeline(object_id: Any, by_line: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """記錄上的管線號對到設計管線：先原樣比；對不上再去掉結尾的公稱直徑（PL8303-100 → PL8303）。

    2026-09-24 業務確認「-100」是公稱直徑。設計資料若寫了公稱直徑且與去掉的數不同，
    就不是同一條，不配對——寧可判不了，也不把別的管線的依據套過來。
    """
    exact = by_line.get(_key(object_id))
    if exact is not None:
        return exact
    match = _DN_SUFFIX_RE.match(str(object_id or "").strip())
    pipeline = by_line.get(_key(match.group("line"))) if match else None
    if pipeline is None:
        return None
    # 只拿乾淨的公稱直徑（「100」「DN100」）來核；「Φ108X8」是外徑×壁厚，不是公稱直徑，不拿來擋。
    diameter = _DN_RE.match(str(pipeline.get("specification") or ""))
    return pipeline if not diameter or diameter.group(1) == match.group("dn") else None


def _leak_basis(pipeline: dict[str, Any]) -> str | None:
    if pipeline.get("leakTestRequired") is True:
        return "design_leak_test_required"
    if any(word in str(pipeline.get("mediumProperty") or "") for word in ("有毒", "剧毒", "毒性")):
        return "medium_toxic"
    flags = medium_hazard_flags(toxicity=pipeline.get("mediumToxicity"), leak_hazard=pipeline.get("leakHazard"),
                                medium=pipeline.get("medium"))
    if flags["toxic"] is True:
        return "medium_toxic"
    if flags["leakHazard"] is True:
        return "medium_leak_hazard"
    return None


def _grounding_basis(pipeline: dict[str, Any]) -> str | None:
    fire = str(pipeline.get("fireHazard") or "").strip()
    if fire and _FIRE_CLASS_RE.search(fire):
        return "medium_flammable"
    # 设计表「介质特性」栏明写可燃／易燃，同样是设计资料写明的依据，不是按介质名称猜。
    return "medium_flammable" if re.search(r"可燃|易燃", str(pipeline.get("mediumProperty") or "")) else None


_DOMAINS = {("r47", "staticGrounding"): _grounding_basis,
            ("r66", "leakTestConditions"): _leak_basis,
            ("r67", "leakTestMethod"): _leak_basis}


def apply_record_applicability(facts: Any) -> Any:
    """在已合併工程管線事實的業務事實上，為記錄領域補「適用」與依據；其餘一律不動。"""
    if not isinstance(facts, dict):
        return facts
    pipelines = ((facts.get("project") or {}).get("pipelines") or []) if isinstance(facts.get("project"), dict) else []
    by_line = {}
    for pipeline in pipelines:
        if isinstance(pipeline, dict) and pipeline.get("pipelineId"):
            by_line.setdefault(_key(pipeline["pipelineId"]), pipeline)
    for (namespace, domain_key), decide in _DOMAINS.items():
        block = (facts.get(namespace) or {}).get(domain_key) if isinstance(facts.get(namespace), dict) else None
        for domain in (block or {}).get("domains") or []:
            if not isinstance(domain, dict) or "applicable" in domain:
                continue
            pipeline = _matching_pipeline(domain.get("objectId"), by_line)
            basis = decide(pipeline) if pipeline else None
            if basis:
                domain["applicable"] = True
                domain["applicabilityBasis"] = {"reason": basis, "pipelineId": pipeline["pipelineId"],
                                                "source": deepcopy(pipeline.get("source") or {})}
    return facts
