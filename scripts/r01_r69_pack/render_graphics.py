from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from .render_common import SIGNATURE_MARKERS, TEST_WARNING, output_file_name
from .test_seal import render_test_seal_png, signature_contract


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
    contract = signature_contract(content)
    canvas.setLineWidth(2)
    canvas.roundRect(width - 215, 24, 175, 54, 8, stroke=1, fill=0)
    canvas.setFont(PDF_FONT, 9)
    canvas.drawCentredString(width - 127.5, 55, "TEST｜测试专用章")
    canvas.drawCentredString(width - 127.5, 39, contract["role"] + "｜合成资料")
    canvas.showPage()
    canvas.save()
    return path


def render_test_photo(content: dict, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    path = output / output_file_name(content, "jpg")
    kind = content.get("graphic_kind", "field_photo")
    if kind == "radiographic_film":
        image = _render_film_image(content)
    elif kind == "external_query_screenshot":
        image = _render_query_image(content)
    else:
        image = _render_field_photo_image(content)
    _add_test_badge(image, content)
    exif = Image.Exif()
    signature_marker = SIGNATURE_MARKERS[0]
    exif[270] = f"{TEST_WARNING}|{signature_marker}|{kind}"
    image.convert("RGB").save(
        path,
        quality=92,
        exif=exif,
        comment=f"{TEST_WARNING}|{signature_marker}|{kind}".encode("utf-8"),
    )
    return path


def _image_fonts() -> tuple[ImageFont.ImageFont, ...]:
    try:
        return (
            ImageFont.truetype(FONT_PATH, 52),
            ImageFont.truetype(FONT_PATH, 31),
            ImageFont.truetype(FONT_PATH, 38),
            ImageFont.truetype(FONT_PATH, 24),
        )
    except OSError:
        fallback = ImageFont.load_default()
        return fallback, fallback, fallback, fallback


def _render_field_photo_image(content: dict) -> Image.Image:
    image = Image.new("RGB", (1600, 1000), "#EAF0F6")
    draw = ImageDraw.Draw(image)
    title_font, body_font, warning_font, small_font = _image_fonts()
    draw.rectangle((70, 70, 1530, 930), outline="#264A73", width=7)
    draw.text((110, 105), content.get("title", "现场核验图（测试）"), font=title_font, fill="#264A73")
    draw.rounded_rectangle((180, 280, 1420, 675), radius=36, fill="#D1DDE9", outline="#8998A8", width=5)
    draw.line((260, 475, 1340, 475), fill="#264A73", width=38)
    draw.line((320, 475, 1280, 475), fill="#8998A8", width=105)
    draw.text(
        (220, 710),
        f"对象：{content.get('evidence_object', 'PL8308-TEST 道路穿越施工示意')}",
        font=body_font,
        fill="#233142",
    )
    draw.text((205, 790), "仅验证附件存在性与可读性；不执行OCR，不代表真实现场影像。", font=small_font, fill="#233142")
    draw.text((205, 850), TEST_WARNING, font=warning_font, fill="#B3261E")
    return image


def _render_film_image(content: dict) -> Image.Image:
    image = Image.new("RGB", (1600, 900), "#0D131B")
    draw = ImageDraw.Draw(image)
    title_font, body_font, warning_font, small_font = _image_fonts()
    draw.rectangle((55, 55, 1545, 845), outline="#6F879D", width=6)
    draw.text((95, 90), content.get("title", "射线检测模拟底片"), font=title_font, fill="#E7EEF5")
    draw.rounded_rectangle((120, 220, 1480, 610), radius=28, fill="#172331", outline="#9DB1C4", width=4)
    for index in range(10):
        x = 210 + index * 125
        shade = 62 + (index % 4) * 18
        draw.ellipse((x, 335, x + 72, 407), fill=(shade, shade + 8, shade + 15))
    draw.line((180, 420, 1420, 420), fill="#C5D2DE", width=12)
    draw.line((760, 240, 790, 590), fill="#E0A29D", width=5)
    draw.text((130, 650), f"对象：{content.get('evidence_object', 'W-S06-001／片号TEST-FILM')}", font=body_font, fill="#E7EEF5")
    draw.text((130, 710), "测试模拟底片图，不得作为真实检测底片或检测结论。", font=small_font, fill="#F4B7B2")
    draw.text((130, 770), TEST_WARNING, font=warning_font, fill="#F06B61")
    return image


def _render_query_image(content: dict) -> Image.Image:
    image = Image.new("RGB", (1440, 1000), "#F4F6F9")
    draw = ImageDraw.Draw(image)
    title_font, body_font, warning_font, small_font = _image_fonts()
    draw.rectangle((35, 35, 1405, 965), outline="#264A73", width=5)
    draw.rectangle((35, 35, 1405, 145), fill="#264A73")
    draw.text((80, 66), "外部资格查询测试界面（离线合成）", font=title_font, fill="#FFFFFF")
    draw.rounded_rectangle((110, 210, 1330, 365), radius=18, fill="#FFFFFF", outline="#AEB9C5", width=3)
    draw.text((150, 250), "查询条件：档案编号 TS21********937（已脱敏）", font=body_font, fill="#233142")
    draw.rounded_rectangle((110, 420, 1330, 710), radius=18, fill="#FFFFFF", outline="#AEB9C5", width=3)
    draw.text((150, 465), "测试返回：来源证书页已绑定；有效期按来源年份核验", font=body_font, fill="#233142")
    draw.text((150, 535), f"对象：{content.get('evidence_object', '焊工资格来源证据')}", font=small_font, fill="#5B677A")
    draw.text((150, 610), "本界面未连接官方系统，不代表官方查询结果。", font=small_font, fill="#B3261E")
    draw.text((110, 815), TEST_WARNING, font=warning_font, fill="#B3261E")
    return image


def _add_test_badge(image: Image.Image, content: dict) -> None:
    contract = signature_contract(content)
    badge = Image.open(
        BytesIO(render_test_seal_png(contract["label"], contract["role"]))
    ).convert("RGBA")
    badge.thumbnail((430, 175), Image.Resampling.LANCZOS)
    rgba = image.convert("RGBA")
    rgba.alpha_composite(
        badge,
        (rgba.width - badge.width - 75, rgba.height - badge.height - 70),
    )
    image.paste(rgba.convert("RGB"))
