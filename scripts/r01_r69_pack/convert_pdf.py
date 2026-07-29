from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageStat
from pypdf import PdfReader, PdfWriter

from .render_common import TEST_WARNING, TEST_WARNING_ASCII


SOFFICE = Path(
    "/Users/hankieyooly/.cache/codex-runtimes/"
    "codex-primary-runtime/dependencies/bin/override/soffice"
)
PDFTOPPM = Path(
    "/Users/hankieyooly/.cache/codex-runtimes/"
    "codex-primary-runtime/dependencies/bin/override/pdftoppm"
)


def convert_office_to_pdf(source: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r01-r69-lo-profile-") as profile:
        subprocess.run(
            [
                str(SOFFICE),
                f"-env:UserInstallation=file://{profile}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    path = output_dir / f"{source.stem}.pdf"
    if not path.exists():
        raise RuntimeError(f"LibreOffice did not create {path}")
    reader = PdfReader(path)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata(
        {
            "/Title": source.stem,
            "/Subject": f"{TEST_WARNING} | {TEST_WARNING_ASCII}",
            "/Author": "TEST-资料编制系统",
        }
    )
    rewritten = output_dir / f".{source.stem}.marked.pdf"
    with rewritten.open("wb") as handle:
        writer.write(handle)
    rewritten.replace(path)
    return path


def _page_is_blank(path: Path, page: int) -> bool:
    with tempfile.TemporaryDirectory(prefix="r01-r69-pdf-check-") as temp:
        prefix = Path(temp) / "page"
        subprocess.run(
            [
                str(PDFTOPPM),
                "-f",
                str(page),
                "-singlefile",
                "-png",
                "-r",
                "90",
                str(path),
                str(prefix),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        with Image.open(prefix.with_suffix(".png")) as image:
            grayscale = image.convert("L")
            extrema = ImageStat.Stat(grayscale).extrema[0]
            return extrema[1] - extrema[0] < 2


def validate_pdf(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists() or path.stat().st_size == 0:
        return ["PDF不存在或为空"]
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            errors.append("PDF不得加密")
            return errors
        if not reader.pages:
            errors.append("PDF页数为零")
            return errors
        for index, page in enumerate(reader.pages, start=1):
            if float(page.mediabox.width) <= 0 or float(page.mediabox.height) <= 0:
                errors.append(f"第{index}页尺寸无效")
        for page_number in sorted({1, len(reader.pages)}):
            if _page_is_blank(path, page_number):
                errors.append(f"第{page_number}页疑似空白")
    except Exception as exc:
        errors.append(f"PDF读取失败：{exc}")
    return errors
