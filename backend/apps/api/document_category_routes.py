"""改一份资料的类别（0817 第 2 条的配套）。

## 为什么必须有这个

上传后自动识别类别，**自动分类一定会错**——第 1 条本身就是分类错的例子。
没有纠正出口的自动化，用户错一次就没有办法了：他看得见分错了，
却只能重新传一遍，或者眼睁睁看着规则去错的地方取证、把资料判成缺项。

## 一条口径

改完要把 `materialCategorySource` 标成 `manual`。
「系统猜的」和「人改的」必须分得开：

- 分不开的话，下次自动分类升级、想批量重跑时，
  没有任何办法把人工改过的那些排除掉，会被一把冲掉；
- 界面上也没法诚实地说「这是识别的」还是「这是你定的」。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, Request

from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import repo
from libs.material_auto_classify import known_categories

document_category_router = APIRouter()


@document_category_router.patch("/projects/{project_id}/documents/{document_id}/material-category")
def update_document_material_category(
    request: Request,
    project_id: str,
    document_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_role: str | None = Header(default=None, alias="X-Role"),
):
    from apps.api.routes import document_read_error, idempotent, mutation_guard

    category = str(body.get("materialCategory") or "").strip()
    if not category:
        return fail(errors.VALIDATION_ERROR, request, message="资料类别不能为空。")
    # 只接受配置里存在的类别。允许任意字符串的话，规则按类别取证时
    # 永远取不到——而界面上看着「已经归好类了」。
    allowed = known_categories()
    if allowed and category not in allowed:
        return fail(
            errors.VALIDATION_ERROR,
            request,
            message="资料类别不存在。",
            data={"allowed": sorted(allowed)},
        )

    document = next(
        (
            item
            for item in repo.state.get("documents", [])
            if str(item.get("id")) == str(document_id)
            and str(item.get("projectId")) == str(project_id)
        ),
        None,
    )
    if not document:
        return fail(errors.NOT_FOUND, request, message="资料不存在。")

    def produce():
        guard = mutation_guard(request, project_id, x_role=x_role)
        if guard:
            return guard
        access_error = document_read_error(request, project_id, document)
        if access_error:
            return access_error
        before = document.get("materialCategory")
        document["materialCategory"] = category
        # 「系统猜的」和「人改的」必须分得开：分不开的话，
        # 下次想批量重跑自动分类时没办法把人工改过的排除掉，会被一把冲掉。
        document["materialCategorySource"] = "manual"
        repo.add_audit(f"修正资料类别 {before} -> {category}", "Document", document_id)
        return ok(
            {
                "documentId": document_id,
                "materialCategory": category,
                "previousCategory": before,
                "materialCategorySource": "manual",
            },
            request,
        )

    return idempotent(request, idempotency_key, produce, fingerprint_source=body)
