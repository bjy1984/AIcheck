"""树接口不该替详情页把数据先背一遍。

## 线上实测（2026-08-16，建设方首屏）

    GET /projects/P-2026-8FC0B5/tree   382 KB   708 ms

按字段拆开：

    requirementsSummary   349 KB   ← 91%
    templateId              2.4 KB
    actions                 1.9 KB
    其余全部                 ~28 KB

69 个节点，每个都拖着 `requirements` 和 `missingRequirements` 两份完整明细
（两个数组字节数一模一样——同一批需求装了两遍），每项还带着 source 文档路径、
revision、updatedAt、minConfidence、evidenceItems……

而树上只用四个计数和缺失项的 name（Workbench.vue 的
inspectionProjectNodeRows）。明细在 /nodes/{id}/package 里另发一份，
点开哪个节点才取哪个。

## 判据

- 树里只留计数 + 缺失项的身份（id/materialTypeCode）和名字
- **不能顺手把计数也砍了**：树上的进度条就靠它们
- 详情那条路径必须保持完整——瘦身只针对列表
"""

from __future__ import annotations

from apps.api.routes import slim_requirements_summary

FULL = {
    "requiredCount": 3,
    "satisfiedCount": 1,
    "missingCount": 2,
    "progressPercent": 33,
    "hasRequirementDetails": True,
    "source": "nodeEvidenceLinks",
    "readyForAi": False,
    "supportingDocumentCount": 0,
    "requirements": [
        {
            "id": "MRP-1-design_license-05AB35",
            "name": "设计单位许可证",
            "source": "docs/工程监检资料映射表.md",
            "revision": 1,
            "updatedAt": "2026-06-26 08:30:00",
            "evidenceItems": ["设计许可证机构名称", "许可范围", "许可级别", "有效期", "印章"],
            "minConfidence": 0.85,
        }
    ],
    "missingRequirements": [
        {
            "id": "MRP-1-design_license-05AB35",
            # 真实需求项带 materialTypeCode（业务包 requiredMaterials 里就有）。
            # 夹具漏了它的话，用例只会测到「取到 None 也叫通过」。
            "materialTypeCode": "design_license",
            "name": "设计单位许可证",
            "source": "docs/工程监检资料映射表.md",
            "revision": 1,
            "evidenceItems": ["设计许可证机构名称", "许可范围"],
        }
    ],
}


def test_计数一个都不能少():
    """树上的进度条就靠这几个数，砍了它们等于把功能删了。"""
    slim = slim_requirements_summary(FULL)
    assert slim["requiredCount"] == 3
    assert slim["satisfiedCount"] == 1
    assert slim["missingCount"] == 2
    assert slim["progressPercent"] == 33
    assert slim["hasRequirementDetails"] is True


def test_缺失项只留身份和名字():
    """砍的是**明细**，不是**身份**。

    第一版把 materialTypeCode 也砍了，只留 id + name——于是调用方只能靠
    显示名去对，而显示名会随配置改动。test_business_pack 立刻红了，
    我当时误判成「既有失败、与我无关」，直到查到提交记录才发现是自己砍的。

    id / materialTypeCode 都是短字符串，占不了几个字节；
    真正撑大响应的是 source 路径、evidenceItems、revision 那些。
    """
    slim = slim_requirements_summary(FULL)
    item = slim["missingRequirements"][0]
    assert item == {
        "id": "MRP-1-design_license-05AB35",
        "materialTypeCode": "design_license",
        "name": "设计单位许可证",
    }
    assert "source" not in item, "文档路径是详情页的东西"
    assert "evidenceItems" not in item, "证据项清单在详情里，列表页不需要"
    assert "revision" not in item


def test_名称按前端同一套优先级取():
    """**真实需求项没有 name 字段**——名称在 materialTypeName 里。

    线上实测：树上「缺失资料名」这一列本来就是空的（前端 `.map(r => r.name)`
    一直取到 undefined），只是没人注意，我做瘦身时才把它暴露出来。
    取法要和前端 requirementDisplayName 一致，否则同一条资料在列表和详情里
    会显示成两个名字——那比没有名字更让人怀疑数据。
    """
    real_item = {
        "id": "MRP-1",
        "materialTypeName": "设计单位许可证",
        "reviewContent": "设计单位许可资质",
        "nodeName": "设计单位许可资质",
    }
    slim = slim_requirements_summary({"missingRequirements": [real_item]})
    assert slim["missingRequirements"][0]["name"] == "设计单位许可证"

    # 依次降级
    assert (
        slim_requirements_summary({"missingRequirements": [{"reviewContent": "审查内容"}]})[
            "missingRequirements"
        ][0]["name"]
        == "审查内容"
    )
    # 占位分支写的是 name，也要认
    assert (
        slim_requirements_summary({"missingRequirements": [{"name": "资料要求明细未配置"}]})[
            "missingRequirements"
        ][0]["name"]
        == "资料要求明细未配置"
    )
    # 什么都没有时给个可读的兜底，不要 null——前端拿 null 会显示成空白
    assert (
        slim_requirements_summary({"missingRequirements": [{"id": "X"}]})["missingRequirements"][0][
            "name"
        ]
        == "未命名资料"
    )


def test_不再下发完整需求明细():
    """requirements 和 missingRequirements 长度一样——同一批需求装了两遍。"""
    slim = slim_requirements_summary(FULL)
    assert "requirements" not in slim


def test_体积确实降下来了():
    import json

    full_size = len(json.dumps(FULL, ensure_ascii=False))
    slim_size = len(json.dumps(slim_requirements_summary(FULL), ensure_ascii=False))
    assert slim_size < full_size / 2, f"瘦身无效：{full_size} → {slim_size}"


def test_空摘要不炸():
    slim = slim_requirements_summary({})
    assert slim["requiredCount"] == 0
    assert slim["missingRequirements"] == []


def test_树接口用瘦身版而详情不用():
    """瘦身只针对列表。详情页少了明细就没法核对了——
    **优化体积时最容易顺手削掉别人正在用的东西**。"""
    import inspect

    from apps.api import routes

    source = inspect.getsource(routes)
    # 锚点要唯一：filter_node_groups_for_scope 在项目详情里也出现（那处只做计数），
    # 按它定位会落到无关的函数上——**判据不精确的测试，失败时误导人去改对的代码**。
    tree_at = source.index('group["nodes"] = [')
    tree_block = source[tree_at : tree_at + 400]
    assert "slim=True" in tree_block, "树接口要用瘦身版"

    # 详情侧（节点包）不能带 slim=True
    package_at = source.index("def node_package")
    package_block = source[package_at : package_at + 4000]
    assert "slim=True" not in package_block, "详情页仍需完整明细"
