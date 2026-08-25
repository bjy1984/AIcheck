"""Office 资料在线预览的路由（从 routes.py 拆出）。

## 为什么先拆这一块

routes.py 是 32,226 行、368 路由的巨石（issue #12 A-2），一次性拆完是多日工程，
而且会制造淹没真实改动的巨型 diff。所以走「按业务域增量拆分」——先拆一块，
把路子走通，也给巨石棘轮一个「确实能缩」的证明。

选它是因为它自成一体：只依赖 document_read_scope_error 做范围校验、
libs/office_preview 做转换、object_storage 存产物，与其余 360 多个路由没有耦合。

## 这块代码踩过的坑（都写在各函数的注释里）

- 缓存判据用「能否签发 URL」而不是「对象是否存在」——签发是纯计算，
  于是缓存永远命中、转换一次没跑过；
- 预览地址返回 MinIO 预签名 URL，那是服务器回环，浏览器取不到。
"""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from libs.content_hash import normalized_content_hash
from libs.contracts import errors
from libs.contracts.responses import fail, ok
from libs.db.repository import repo
from libs.integrations.storage import ObjectStorageUnavailable, object_storage
from libs.office_preview import (
    CONVERTIBLE_SUFFIXES,
    OfficeConversionFailed,
    OfficeConversionUnavailable,
    convert_office_to_pdf,
    office_preview_available,
)

router = APIRouter()


OFFICE_PREVIEW_BUCKET = "documents"


def office_preview_object_name(document_id: str, content_hash: str) -> str:
    """转换产物的对象名。

    按内容哈希命名：同一版本只转一次，内容变了哈希就变、缓存自然失效，
    不需要手动清理。
    """
    return f"office-preview/{document_id}/{content_hash}.pdf"


def ensure_office_preview_pdf(document: dict[str, Any], file_name: str) -> bytes:
    """确保转换产物存在并返回 PDF 字节。已有缓存则直接取回。"""
    version = repo.current_version(str(document.get("id") or "")) or {}
    content_hash = normalized_content_hash(version.get("hash"))
    object_name = office_preview_object_name(str(document.get("id") or ""), content_hash)
    if office_preview_cached(object_name):
        return object_storage.get_bytes(OFFICE_PREVIEW_BUCKET, object_name)
    source_url = repo.document_storage_url(document, fallback_prefix="preview")
    source_signed = object_storage.presigned_get_url(source_url, internal=True)
    if not source_signed:
        raise OfficeConversionFailed("该资料没有可用的存储对象，无法预览。")
    with urllib.request.urlopen(source_signed, timeout=60) as response:
        source_bytes = response.read()
    pdf_bytes = convert_office_to_pdf(source_bytes, file_name)
    object_storage.put_bytes(
        OFFICE_PREVIEW_BUCKET, object_name, pdf_bytes, content_type="application/pdf"
    )
    return pdf_bytes


def office_preview_cached(object_name: str) -> bool:
    """转换产物是否已在对象存储里。

    必须实查 stat，不能拿 presigned_get_url 的返回值当判据：签发是纯计算，
    对不存在的对象照样给出一个合法 URL。踩过这个坑——接口返回 200 带地址，
    前端取回 404，而转换从头到尾没执行过。
    """
    try:
        return bool(object_storage.object_metadata(OFFICE_PREVIEW_BUCKET, object_name))
    except ObjectStorageUnavailable as exc:
        detail = str(exc).lower()
        if any(
            marker in detail
            for marker in ("nosuchkey", "nosuchobject", "nosuchversion", "object does not exist")
        ):
            return False
        raise
    except Exception:  # noqa: BLE001 — 存储侧异常五花八门（网络、权限、S3Error），
        # 这里不关心是哪一种：查不动就当没有。多转一次只浪费几秒，
        # 判成「有」则是返回一个坏链接，代价不对等。
        return False


@router.get("/projects/{project_id}/documents/{document_id}/office-preview/content")
def document_office_preview_content(request: Request, project_id: str, document_id: str):
    """直接返回转换后的 PDF 字节。

    不能给前端一个 MinIO 预签名地址：那个地址是 http://127.0.0.1:19000/...，
    指向的是**服务器自己的回环**，用户浏览器根本到不了——线上实测过，接口 200、
    地址合法，浏览器一取就失败，界面显示「Office 预览服务不可用」，而服务好好的。

    已经能用的 PDF/图片预览走的就是「经 API 取字节 → 前端 createObjectURL」，
    这里沿用同一套路：MinIO 不必对外暴露，鉴权也仍在 API 这一层。
    """
    # 惰性导入：本模块由 routes.py 在导入期挂载，模块级反向导入会成环。
    # document_read_scope_error 依赖 routes 里的一串鉴权辅助，下沉它会牵出更多，
    # 不在这次增量拆分的范围内。
    from apps.api.routes import document_read_scope_error

    scope_error = document_read_scope_error(request, project_id, document_id)
    if scope_error:
        return scope_error
    document = repo.find_one("documents", document_id)
    if not document:
        return fail(errors.NOT_FOUND, request)
    if not office_preview_available():
        return fail(
            errors.OFFICE_PREVIEW_UNAVAILABLE,
            request,
            message="Office 预览服务未就绪（运行环境缺少 LibreOffice）。",
            http_status=503,
        )
    file_name = str(document.get("fileName") or "")
    suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if suffix not in CONVERTIBLE_SUFFIXES:
        return fail(
            errors.VALIDATION_ERROR,
            request,
            message=f"{suffix or '该'} 格式不支持 Office 在线预览。",
        )
    try:
        pdf_bytes = ensure_office_preview_pdf(document, file_name)
    except (OfficeConversionUnavailable, OfficeConversionFailed) as exc:
        return fail(
            errors.OFFICE_PREVIEW_UNAVAILABLE, request, message=str(exc), http_status=503
        )
    except ObjectStorageUnavailable as exc:
        return fail(
            errors.OBJECT_STORAGE_REQUIRED,
            request,
            message=str(exc) or "对象存储不可用，无法生成预览。",
            http_status=503,
        )
    if not pdf_bytes:
        return fail(
            errors.OFFICE_PREVIEW_UNAVAILABLE,
            request,
            message="Office 转换未产出内容。",
            http_status=503,
        )
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get("/projects/{project_id}/documents/{document_id}/office-preview")
def document_office_preview(request: Request, project_id: str, document_id: str):
    """Office 文件的在线预览：转成 PDF，复用已验证可用的 PDF 预览路径。

    这个项目的资料全是 .docx，此前在系统里完全无法查看——界面只提示「请下载后用
    Word 打开」，监检得离开系统、在本地比对，再回来填结论。

    先接过 ONLYOFFICE Document Server，卡在转换器 error:-7 未果（详见
    libs/office_preview.py 的说明），改用 LibreOffice headless 转 PDF。
    """
    # 惰性导入：本模块由 routes.py 在导入期挂载，模块级反向导入会成环。
    # document_read_scope_error 依赖 routes 里的一串鉴权辅助，下沉它会牵出更多，
    # 不在这次增量拆分的范围内。
    from apps.api.routes import document_read_scope_error

    scope_error = document_read_scope_error(request, project_id, document_id)
    if scope_error:
        return scope_error
    document = repo.find_one("documents", document_id)
    if not document:
        return fail(errors.NOT_FOUND, request)

    if not office_preview_available():
        return fail(
            errors.OFFICE_PREVIEW_UNAVAILABLE,
            request,
            message="Office 预览服务未就绪（运行环境缺少 LibreOffice）。",
            data={"reason": "LIBREOFFICE_NOT_INSTALLED"},
            http_status=503,
        )

    file_name = str(document.get("fileName") or "")
    suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if suffix not in CONVERTIBLE_SUFFIXES:
        return fail(
            errors.VALIDATION_ERROR,
            request,
            message=f"{suffix or '该'} 格式不支持 Office 在线预览。",
            data={"fileName": file_name, "suffix": suffix},
        )

    version = repo.current_version(document_id) or {}
    content_hash = normalized_content_hash(version.get("hash"))
    if not content_hash:
        return fail(
            errors.NOT_FOUND,
            request,
            message="该资料没有可用的存储对象，无法预览。",
            data={"reason": "STORAGE_OBJECT_MISSING"},
        )

    try:
        # 先把转换做掉（有缓存就直接命中），失败要在这里就报出来，
        # 而不是给前端一个地址、让它取的时候才发现是空的。
        ensure_office_preview_pdf(document, file_name)
    except OfficeConversionUnavailable as exc:
        return fail(
            errors.OFFICE_PREVIEW_UNAVAILABLE,
            request,
            message=str(exc),
            data={"reason": "LIBREOFFICE_NOT_INSTALLED"},
            http_status=503,
        )
    except OfficeConversionFailed as exc:
        return fail(
            errors.OFFICE_PREVIEW_UNAVAILABLE,
            request,
            message=str(exc),
            data={"reason": "OFFICE_CONVERSION_FAILED"},
            http_status=503,
        )
    except ObjectStorageUnavailable as exc:
        return fail(
            errors.OBJECT_STORAGE_REQUIRED,
            request,
            message=str(exc) or "对象存储不可用，无法生成预览。",
            http_status=503,
        )

    return ok(
        {
            "previewType": "pdf",
            # 给 API 路径而不是 MinIO 预签名地址：后者是服务器回环，浏览器到不了
            "url": f"/api/projects/{project_id}/documents/{document_id}/office-preview/content",
            "fileName": f"{Path(file_name).stem or document_id}.pdf",
            "sourceFileName": file_name,
            "readonly": True,
            "convertedFrom": suffix,
        },
        request,
    )
