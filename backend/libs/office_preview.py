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
import os
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
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


class _OfficeHtmlTextParser(HTMLParser):
    BLOCK_TAGS = {"br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")
        elif tag.lower() in {"td", "th"}:
            self.parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1
            return
        if self.ignored_depth:
            return
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def office_html_to_text(value: str) -> str:
    parser = _OfficeHtmlTextParser()
    parser.feed(str(value or ""))
    lines = [re.sub(r"[\t \u00a0]+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def soffice_executable() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


def office_preview_available() -> bool:
    return soffice_executable() is not None


def _convert_office_bytes(data: bytes, file_name: str, target_format: str) -> bytes:
    executable = soffice_executable()
    if not executable:
        raise OfficeConversionUnavailable("LibreOffice 未安装，无法转换 Office 文件。")
    suffix = Path(str(file_name or "")).suffix.lower().lstrip(".")
    if suffix not in CONVERTIBLE_SUFFIXES:
        raise OfficeConversionFailed(f"{suffix or '该'} 格式不支持转换。")
    with tempfile.TemporaryDirectory(prefix="aicheck-office-") as workdir:
        root = Path(workdir)
        source = root / f"source.{suffix}"
        source.write_bytes(data)
        outdir = root / "out"
        outdir.mkdir()
        profile = root / "profile"
        env = {**os.environ, "HOME": str(root)}
        try:
            completed = subprocess.run(
                [
                    executable,
                    "--headless",
                    "--norestore",
                    "--nolockcheck",
                    f"-env:UserInstallation=file://{profile}",
                    "--convert-to",
                    target_format,
                    "--outdir",
                    str(outdir),
                    str(source),
                ],
                capture_output=True,
                timeout=CONVERT_TIMEOUT_SECONDS,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise OfficeConversionFailed(f"Office 转换超时（{CONVERT_TIMEOUT_SECONDS} 秒）。") from exc
        produced = list(outdir.glob(f"*.{target_format}"))
        if not produced:
            detail = (completed.stderr or completed.stdout or b"").decode("utf-8", "replace")
            LOGGER.error("office_convert_failed: %s -> %s | %s", file_name, target_format, detail[:300])
            raise OfficeConversionFailed(f"Office 转换未产出 {target_format.upper()}。")
        return produced[0].read_bytes()


def convert_office_to_pdf(data: bytes, file_name: str) -> bytes:
    """把 Office 文件字节转成 PDF 字节。

    每次转换用独立的临时 profile 目录：LibreOffice 的默认 profile 是单实例锁，
    并发转换会互相阻塞甚至挂死。
    """
    return _convert_office_bytes(data, file_name, "pdf")


def extract_office_text(data: bytes, file_name: str) -> str:
    html_bytes = _convert_office_bytes(data, file_name, "html")
    return office_html_to_text(html_bytes.decode("utf-8", "replace"))
