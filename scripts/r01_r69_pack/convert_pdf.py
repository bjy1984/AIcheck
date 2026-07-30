from __future__ import annotations

from collections import Counter
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image, ImageStat
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .render_common import TEST_WARNING, TEST_WARNING_ASCII


SOFFICE = Path(
    "/Users/hankieyooly/.cache/codex-runtimes/"
    "codex-primary-runtime/dependencies/bin/override/soffice"
)
PDFTOPPM = Path(
    "/Users/hankieyooly/.cache/codex-runtimes/"
    "codex-primary-runtime/dependencies/bin/override/pdftoppm"
)
LO_FONT_DIR = Path(
    "/Users/hankieyooly/.cache/codex-runtimes/"
    "codex-primary-runtime/dependencies/native/libreoffice-headless/libreoffice/"
    "LibreOfficeDev.app/Contents/Resources/fonts/truetype"
)
SYSTEM_CJK_FONT = Path("/Library/Fonts/Arial Unicode.ttf")
XLSX_PREVIEW_ROOT = Path.cwd() / "tmp/r01-r69-xlsx-previews"


def ensure_libreoffice_cjk_font() -> None:
    """Make the installed CJK font visible to the isolated LO bundle."""
    destination = LO_FONT_DIR / "ArialUnicode.ttf"
    if destination.exists() or not SYSTEM_CJK_FONT.exists():
        return
    LO_FONT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SYSTEM_CJK_FONT, destination)


def _mark_pdf(path: Path, title: str) -> None:
    reader = PdfReader(path)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata(
        {
            "/Title": title,
            "/Subject": f"{TEST_WARNING} | {TEST_WARNING_ASCII}",
            "/Author": "TEST-资料编制系统",
        }
    )
    rewritten = path.with_name(f".{path.stem}.marked.pdf")
    with rewritten.open("wb") as handle:
        writer.write(handle)
    rewritten.replace(path)


def convert_office_to_pdf(source: Path, output_dir: Path) -> Path:
    ensure_libreoffice_cjk_font()
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
    _mark_pdf(path, source.stem)
    return path


def _sheet_preview_path(source: Path, sheet_name: str) -> Path:
    safe_name = sheet_name.replace("/", "_")
    return XLSX_PREVIEW_ROOT / source.stem / f"{safe_name}.png"


def _repeated_header_height(image: Image.Image) -> int:
    last_header_row = 0
    scan_height = min(180, image.height)
    for y in range(scan_height):
        colors = Counter(
            image.crop((0, y, image.width, y + 1)).get_flattened_data()
        )
        dark_blue = sum(
            count
            for (red, green, blue), count in colors.items()
            if red < 80 and green < 125 and blue < 165 and blue > red
        )
        if dark_blue >= image.width * 0.5:
            last_header_row = y
    return min(140, max(80, last_header_row + 1))


def _snap_to_gridline(
    image: Image.Image,
    target: int,
    minimum: int,
) -> int:
    """Move a page cut to the nearest preceding full-width row border."""
    lower = max(minimum, target - 48)
    for y in range(target, lower - 1, -1):
        colors = Counter(
            image.crop((0, y, image.width, y + 1)).get_flattened_data()
        )
        color, count = colors.most_common(1)[0]
        red, green, blue = color
        is_light_grid = (
            175 <= red <= 248
            and 175 <= green <= 248
            and 175 <= blue <= 248
            and max(color) - min(color) <= 18
        )
        if is_light_grid and count >= image.width * 0.6:
            return min(image.height, y + 1)
    return min(image.height, target)


def _sheet_page_images(image: Image.Image) -> list[Image.Image]:
    """Split a sheet preview into readable landscape pages.

    The full table width is always retained. Long worksheets are split down the
    rows, and the workbook title/header strip is repeated on continuation pages.
    """
    page_width, page_height = landscape(A4)
    horizontal_margin = 28
    vertical_margin = 28
    footer_height = 18
    usable_width = page_width - (2 * horizontal_margin)
    usable_height = page_height - (2 * vertical_margin) - footer_height
    crop_height = max(180, int(image.width * usable_height / usable_width))

    rgb = image.convert("RGB")
    if rgb.height <= crop_height:
        return [rgb]

    # Detect the lower dark-blue band (row 4 table header), rather than using
    # a fixed pixel count that might omit a narrow sheet's column labels.
    repeated_header = _repeated_header_height(rgb)
    body_capacity = max(120, crop_height - repeated_header)
    pages: list[Image.Image] = []

    first_bottom = _snap_to_gridline(
        rgb,
        min(rgb.height, crop_height),
        repeated_header + 120,
    )
    pages.append(rgb.crop((0, 0, rgb.width, first_bottom)))
    cursor = first_bottom
    header = rgb.crop((0, 0, rgb.width, repeated_header))
    while cursor < rgb.height:
        target = min(rgb.height, cursor + body_capacity)
        body_bottom = (
            rgb.height
            if target == rgb.height
            else _snap_to_gridline(rgb, target, cursor + 120)
        )
        body = rgb.crop((0, cursor, rgb.width, body_bottom))
        page = Image.new("RGB", (rgb.width, header.height + body.height), "white")
        page.paste(header, (0, 0))
        page.paste(body, (0, header.height))
        pages.append(page)
        cursor = body_bottom
    return pages


def convert_xlsx_to_pdf(
    source: Path,
    output_dir: Path,
    sheet_names: list[str],
) -> Path:
    """Create the XLSX paired PDF from artifact-tool's verified previews.

    LibreOffice's default Calc export may paginate wide tables horizontally.
    The preview-based conversion enforces one-page-wide output while allowing
    long tables to continue vertically at a readable scale.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{source.stem}.pdf"
    missing = [
        path
        for path in (_sheet_preview_path(source, name) for name in sheet_names)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "缺少工作表预览，无法生成适宽PDF：" + "、".join(map(str, missing))
        )

    page_width, page_height = landscape(A4)
    horizontal_margin = 28
    vertical_margin = 28
    footer_height = 18
    usable_width = page_width - (2 * horizontal_margin)
    usable_height = page_height - (2 * vertical_margin) - footer_height
    pdf = canvas.Canvas(str(output), pagesize=(page_width, page_height))
    pdf.setTitle(source.stem)
    pdf.setSubject(f"{TEST_WARNING} | {TEST_WARNING_ASCII}")
    pdf.setAuthor("TEST-资料编制系统")

    total_sheets = len(sheet_names)
    for sheet_index, sheet_name in enumerate(sheet_names, start=1):
        preview_path = _sheet_preview_path(source, sheet_name)
        with Image.open(preview_path) as original:
            page_images = _sheet_page_images(original)
        for page_index, page_image in enumerate(page_images, start=1):
            scale = min(
                usable_width / page_image.width,
                usable_height / page_image.height,
            )
            draw_width = page_image.width * scale
            draw_height = page_image.height * scale
            x = (page_width - draw_width) / 2
            y = vertical_margin + footer_height + (usable_height - draw_height) / 2
            pdf.drawImage(
                ImageReader(page_image),
                x,
                y,
                draw_width,
                draw_height,
                preserveAspectRatio=True,
                mask="auto",
            )
            pdf.setFont("Helvetica", 7)
            pdf.setFillColorRGB(0.28, 0.34, 0.41)
            footer = (
                f"{source.stem} | sheet {sheet_index}/{total_sheets} "
                f"| page {page_index}/{len(page_images)} | {TEST_WARNING_ASCII}"
            )
            pdf.drawCentredString(page_width / 2, vertical_margin, footer)
            pdf.showPage()
    pdf.save()
    _mark_pdf(output, source.stem)
    return output


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
