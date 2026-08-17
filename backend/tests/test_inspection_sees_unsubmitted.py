"""施工方一上传，监检就能看见——但要标出还没正式提交（0817 第 8 条）。

## 用户要的

    「文件上传后，不用通过检查端，监检平台直接能看到，监检平台可以手动通过」

## 原先卡在哪

节点包里对 inspection 角色做了硬过滤：只保留走过提交流程的资料。
于是监检在界面上**根本不知道有这份资料存在**——施工方以为传了，
监检以为没传，两边都没错，事情就卡在那里。

## 但去掉门不等于去掉区分

如果只是把过滤删掉，监检会以为施工方已经正式交付了。
所以每条都带 submittedToInspection：看得见，也看得出还没提交。

**「隐藏」和「不加区分地显示」都是错的，正确的是显示并标注。**
"""

from __future__ import annotations

from pathlib import Path

ROUTES = Path(__file__).resolve().parents[1] / "apps" / "api" / "routes.py"


def _node_package_inspection_block() -> str:
    source = ROUTES.read_text(encoding="utf-8")
    start = source.index('if effective_role == "inspection":')
    return source[start : start + 2000]


def test_不再按已提交过滤掉资料():
    block = _node_package_inspection_block()
    for pattern in (
        'bindings = [item for item in bindings if str(item.get("id") or "") in submitted_binding_ids]',
        'project_files = [\n            item for item in project_files if str(item.get("id") or "") in submitted_document_ids\n        ]',
    ):
        assert pattern not in block, "监检又看不到未提交的资料了——施工方传了他也不知道"


def test_每条都标出有没有正式提交():
    """看得见，也要看得出还没提交。少了这个标记，监检会以为已经交付了。"""
    block = _node_package_inspection_block()
    assert block.count("submittedToInspection") >= 3, (
        "bindings / project_bindings / project_files 三处都要带提交标记"
    )


def test_不直接改仓库里的对象():
    """用 {**item, ...} 造新字典。

    直接给 repo.state 里的对象塞字段，这个只为展示服务的标记会被写进库，
    以后谁也说不清它是业务数据还是渲染用的临时值。
    """
    block = _node_package_inspection_block()
    assert "{**item, \"submittedToInspection\"" in block, (
        "要造新字典，不要就地改仓库对象"
    )


def test_建设方视角没被一起放开():
    """M-11 修的是「建设方看到的比监检还多」。

    这次放开的是监检，出资方的口径不动——否则等于把当初那个问题原样放回去。
    """
    source = ROUTES.read_text(encoding="utf-8")
    start = source.index("elif observer_view:")
    block = source[start : start + 900]
    assert "SUBMITTED_DOCUMENT_BINDING_STATUSES" in block, "建设方的过滤被误删了"
