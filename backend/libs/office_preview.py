"""Office 文件转 PDF，供在线预览（L-4）。

## 为什么不是 ONLYOFFICE

先接的 ONLYOFFICE Document Server：镜像 3.3 GB、需 2–4 GB 内存、社区版 AGPL v3，
而且实测卡在转换器 error:-7 / x2t code=88——同一文件手动跑 x2t 成功、DS 服务
调用就失败，排查多轮未果。

改用 LibreOffice headless 转 PDF：
- 复用现有 PDF 预览路径（已验证可用），前端不必再嵌第三方 viewer；
- 资源占用约为 DS 的十分之一，无 AGPL 顾虑；
- 代价是不能在线编辑、排版保真度略低于原生 Word——审查场景只需要「看着原文
  核对字段」，这个代价可以接受。

## 产物缓存

转换结果按「源对象 + 内容哈希」存进对象存储，同一版本只转一次。内容变了哈希就变，
缓存自然失效，不需要手动清。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

LOGGER = logging.getLogger("aicheck.office_preview")

# 能转 PDF 的 Office 格式。范围保守：只列监检资料里真实出现过的，
# 避免给用户「什么都能预览」的错觉。
CONVERTIBLE_SUFFIXES = {"doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "rtf"}

CONVERT_TIMEOUT_SECONDS = 180


class OfficeConversionUnavailable(RuntimeError):
    """LibreOffice 不可用（未安装或启动失败）。"""


class OfficeConversionFailed(RuntimeError):
    """LibreOffice 在位，但这份文件转不出来。"""


def soffice_executable() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


def office_preview_available() -> bool:
    return soffice_executable() is not None


def convert_office_to_pdf(data: bytes, file_name: str) -> bytes:
    """把 Office 文件字节转成 PDF 字节。

    每次转换用独立的临时 profile 目录：LibreOffice 的默认 profile 是单实例锁，
    并发转换会互相阻塞甚至挂死。
    """
    executable = soffice_executable()
    if not executable:
        raise OfficeConversionUnavailable(
            "LibreOffice 未安装，无法生成 Office 预览。"
        )

    suffix = Path(str(file_name or "")).suffix.lower().lstrip(".")
    if suffix not in CONVERTIBLE_SUFFIXES:
        raise OfficeConversionFailed(f"{suffix or '该'} 格式不支持转换为 PDF 预览。")

    with tempfile.TemporaryDirectory(prefix="aicheck-office-") as workdir:
        root = Path(workdir)
        source = root / f"source.{suffix}"
        source.write_bytes(data)
        outdir = root / "out"
        outdir.mkdir()
        profile = root / "profile"

        try:
            completed = subprocess.run(
                [
                    executable,
                    "--headless",
                    "--norestore",
                    "--nolockcheck",
                    f"-env:UserInstallation=file://{profile}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(outdir),
                    str(source),
                ],
                capture_output=True,
                timeout=CONVERT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OfficeConversionFailed(
                f"Office 转换超时（{CONVERT_TIMEOUT_SECONDS} 秒）。"
            ) from exc

        produced = list(outdir.glob("*.pdf"))
        if not produced:
            # LibreOffice 失败时经常仍以 0 退出，所以判据是「有没有产物」而不是退出码
            detail = (completed.stderr or completed.stdout or b"").decode("utf-8", "replace")
            LOGGER.error("office_convert_failed: %s | %s", file_name, detail[:300])
            raise OfficeConversionFailed("Office 转换未产出 PDF，请下载后查看原文。")

        return produced[0].read_bytes()
