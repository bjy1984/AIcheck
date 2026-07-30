from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from .render_common import TEST_WARNING, output_file_name


FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
PDF_FONT = "ArialUnicode"


def _register_pdf_font() -> None:
    if PDF_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(PDF_FONT, FONT_PATH))


def render_pdf_graphic(content: dict, master: dict, output: Path) -> Path:
    del master
    output.mkdir(parents=True, exist_ok=True)
    path = output / output_file_name(content, "pdf")
    _register_pdf_font()
    width, height = landscape(A4)
    canvas = Canvas(str(path), pagesize=(width, height))
    canvas.setTitle(content.get("title", "穿越结构图"))
    canvas.setAuthor("TEST-资料编制系统")
    canvas.setFont(PDF_FONT, 17)
    canvas.setFillColor(colors.HexColor("#264A73"))
    canvas.drawCentredString(width / 2, height - 45, content.get("title", "穿越结构与焊缝布置图"))
    canvas.setFont(PDF_FONT, 9)
    canvas.setFillColor(colors.HexColor("#5B677A"))
    canvas.drawCentredString(
        width / 2,
        height - 65,
        f"文件编号：{content.get('document_number', content.get('logical_id', ''))}　"
        f"版本：{content.get('revision', 'A')}　日期：{content.get('date', '')}",
    )

    left, right, y = 80, width - 80, height / 2
    canvas.setStrokeColor(colors.HexColor("#8998A8"))
    canvas.setLineWidth(18)
    canvas.line(left, y, right, y)
    canvas.setStrokeColor(colors.HexColor("#264A73"))
    canvas.setLineWidth(6)
    canvas.line(left - 45, y, right + 45, y)
    canvas.setFont(PDF_FONT, 10)
    canvas.setFillColor(colors.HexColor("#233142"))
    canvas.drawCentredString(width / 2, y + 34, "道路穿越长度 18 m｜套管 Φ273×7｜载管 20# Φ108×4")
    for x, label in (
        (left + 110, "W-S04-001"),
        (width / 2, "W-S04-002"),
        (right - 110, "W-S04-003"),
    ):
        canvas.setStrokeColor(colors.HexColor("#B3261E"))
        canvas.setLineWidth(2)
        canvas.line(x, y - 25, x, y + 25)
        canvas.setFillColor(colors.HexColor("#B3261E"))
        canvas.drawCentredString(x, y - 42, label)

    for x, label in (
        (left + 40, "11 kg 镁阳极 A"),
        (right - 40, "11 kg 镁阳极 B"),
    ):
        canvas.setFillColor(colors.HexColor("#C98B2E"))
        canvas.rect(x - 30, y - 100, 60, 22, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#233142"))
        canvas.drawCentredString(x, y - 116, label)
        canvas.setStrokeColor(colors.HexColor("#C98B2E"))
        canvas.line(x, y - 78, x, y - 12)

    canvas.setStrokeColor(colors.HexColor("#264A73"))
    canvas.rect(width / 2 - 35, y + 86, 70, 40, fill=0, stroke=1)
    canvas.drawCentredString(width / 2, y + 102, "测试桩")
    canvas.line(width / 2, y + 86, width / 2, y + 20)
    canvas.drawString(left, 115, "绝缘支撑：按 2.0 m 间距设置；端部密封；排流连接：TEST-DR-001")
    canvas.setFillColor(colors.HexColor("#B3261E"))
    canvas.setFont(PDF_FONT, 12)
    canvas.drawCentredString(width / 2, 50, TEST_WARNING)
    canvas.showPage()
    canvas.save()
    return path


def render_test_photo(content: dict, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    path = output / output_file_name(content, "jpg")
    image = Image.new("RGB", (1600, 1000), "#EAF0F6")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype(FONT_PATH, 52)
        body_font = ImageFont.truetype(FONT_PATH, 31)
        warning_font = ImageFont.truetype(FONT_PATH, 38)
    except OSError:
        title_font = body_font = warning_font = ImageFont.load_default()
    draw.rectangle((70, 70, 1530, 930), outline="#264A73", width=7)
    draw.text((110, 105), "施工照片占位附件（测试）", font=title_font, fill="#264A73")
    draw.rounded_rectangle((180, 280, 1420, 675), radius=36, fill="#D1DDE9", outline="#8998A8", width=5)
    draw.line((260, 475, 1340, 475), fill="#264A73", width=38)
    draw.line((320, 475, 1280, 475), fill="#8998A8", width=105)
    draw.text((470, 710), "PL8308-TEST 道路穿越施工示意", font=body_font, fill="#233142")
    draw.text((205, 805), "仅验证附件存在性与可读性；不执行OCR，不代表现场影像。", font=body_font, fill="#233142")
    draw.text((245, 870), TEST_WARNING, font=warning_font, fill="#B3261E")
    exif = Image.Exif()
    exif[270] = TEST_WARNING
    image.save(path, quality=92, exif=exif, comment=TEST_WARNING.encode("utf-8"))
    return path

