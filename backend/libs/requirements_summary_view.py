"""节点资料要求摘要的瘦身视图：树、监检总览用（从 routes.py 挪出）。"""
from __future__ import annotations

from typing import Any


def _requirement_display_name(item: dict[str, Any]) -> str:
    """需求项对人显示的名字。

    与前端 requirementDisplayName 同一套优先级——两处写不一致时，
    同一条资料在列表和详情里会显示成两个名字，那比没有名字更让人怀疑数据。
    """
    for key in ("materialTypeName", "reviewContent", "name", "materialTypeCode"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return "未命名资料"


def slim_requirements_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """树视图用的瘦身版摘要：只留计数和缺失项名称。

    实测（2026-08-16，建设方首屏）：/tree 返回 382 KB，其中
    requirementsSummary 一个字段占 349 KB——**91%**。69 个节点，
    每个都拖着 requirements 和 missingRequirements 两份完整明细
    （两个数组长度一模一样，同一批需求装了两遍），每项还带着
    source 文档路径、revision、updatedAt、minConfidence、evidenceItems……

    而树上只用到四个计数和缺失项的 name（见 Workbench.vue
    inspectionProjectNodeRows）。明细在 /nodes/{id}/package 里另发一份，
    点开哪个节点才取哪个——**列表页不该替详情页把数据先背一遍**。
    """
    return {
        "requiredCount": summary.get("requiredCount", 0),
        "satisfiedCount": summary.get("satisfiedCount", 0),
        "missingCount": summary.get("missingCount", 0),
        "progressPercent": summary.get("progressPercent", 0),
        "hasRequirementDetails": summary.get("hasRequirementDetails", False),
        "supportingDocumentCount": summary.get("supportingDocumentCount", 0),
        # 树上只显示名字。带 id 是为了点进去能对上，不是为了展示。
        #
        # 名称的取法要和前端 requirementDisplayName 一致：
        # materialTypeName → reviewContent → name → materialTypeCode。
        # **真实需求项根本没有 name 字段**——名称在 materialTypeName 里，
        # 只有「明细未配置」那个占位分支才写 name。所以前端那句
        # `.map(r => r.name)` 一直取到 undefined，缺失资料名这一列本来就是空的，
        # 只是没人注意；我做瘦身时才把它暴露出来。
        # materialTypeCode 要留：它是这条需求的**身份**，不是明细。
        # 瘦身那次把它一起砍了（76fbcf2），于是调用方只能靠显示名去对，
        # 而显示名会随配置改动——test_business_pack 立刻红了，我当时
        # 误判成「既有失败、与我无关」。砍大字段没错，砍身份是错的。
        "missingRequirements": [
            {"id": item.get("id"), "materialTypeCode": item.get("materialTypeCode"), "name": _requirement_display_name(item)}
            for item in (summary.get("missingRequirements") or [])
            if isinstance(item, dict)
        ],
    }


def overview_node_view(node: dict[str, Any]) -> dict[str, Any]:
    """监检总览用的节点：需求项只留展开详情要的字段（2026-11-03 生产 670KB）。

    完整需求项每条带 source、revision、evidenceItems……69 个节点 × 两份
    （requirements 与 missingRequirements 同一批对象）就是几百 KB。总览展开
    只显示名称、必传与否、齐没齐、挂了哪些文件；明细点进节点再取。
    """
    summary = node.get("requirementsSummary") or {}
    keep = ("id", "materialTypeCode", "materialTypeName", "fileContent", "name", "requiredType", "fulfilled", "matchedFiles", "matchedFileNames")
    return {
        **node,
        "requirementsSummary": {
            **slim_requirements_summary(summary),
            "requirements": [
                {key: item.get(key) for key in keep if key in item}
                for item in (summary.get("requirements") or [])
                if isinstance(item, dict)
            ],
        },
    }
