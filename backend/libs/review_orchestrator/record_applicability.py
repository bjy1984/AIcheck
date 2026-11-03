"""施工记录的适用性：按管线号到设计管线事实里找依据，只宣告「适用」，不宣告「不适用」。

2026-09-24 业务确认的口径：
- R66／R67 泄漏试验：设计表的泄漏试验要求打 √，或介质有毒／有泄漏危害性（设计资料明写）即适用；
- R47 静电接地：介质火灾危险性为甲、乙类，或设计表写明介质特性可燃／易燃即适用；
- 判不了就维持「适用性未知 → 证据不足」，不按不适用放过；介质名称本身不拿来猜。
设计文件写明静电接地要求这一路，要等设计事实能交接到这些节点再接。
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
    """记录上的管线号对到设计管线：先原样比；对不上再去掉结尾的公称直径（PL8303-100 → PL8303）。

    2026-09-24 业务确认「-100」是公称直径。设计资料若写了公称直径且与去掉的数不同，
    就不是同一条，不配对——宁可判不了，也不把别的管线的依据套过来。
    """
    exact = by_line.get(_key(object_id))
    if exact is not None:
        return exact
    match = _DN_SUFFIX_RE.match(str(object_id or "").strip())
    pipeline = by_line.get(_key(match.group("line"))) if match else None
    if pipeline is None:
        return None
    # 只拿干净的公称直径（「100」「DN100」）来核；「Φ108X8」是外径×壁厚，不是公称直径，不拿来挡。
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
    """在已合并工程管线事实的业务事实上，为记录领域补「适用」与依据；其余一律不动。"""
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
