from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_CANDIDATES = (
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    source = next((path for path in FONT_CANDIDATES if path.exists()), None)
    if source is None:
        return ImageFont.load_default()
    return ImageFont.truetype(str(source), size)


def signature_contract(content: dict) -> dict[str, str]:
    folder = str(content.get("folder", "V00"))
    logical_id = str(content.get("logical_id", ""))
    if "NDT" in logical_id or "FILM" in logical_id:
        role = "检测报告"
    elif folder == "S05":
        role = "安全附件"
    elif folder in {"B00", "S01", "S02", "S03", "S04", "S06"}:
        role = "工程质量"
    else:
        role = "资料验收"
    return {
        "role": role,
        "label": f"{role}测试专用章",
        "record": "电子签署（测试）",
    }


def render_test_seal_png(label: str, role: str) -> bytes:
    """Render an unmistakably synthetic rectangular TEST badge."""
    width, height = 620, 250
    image = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    red = "#B3261E"
    pale = "#FFF3F1"
    draw.rounded_rectangle(
        (8, 8, width - 8, height - 8),
        radius=32,
        fill=pale,
        outline=red,
        width=9,
    )
    draw.rounded_rectangle(
        (25, 25, width - 25, height - 25),
        radius=24,
        outline=red,
        width=3,
    )
    draw.text((42, 38), "TEST", font=_font(58), fill=red)
    draw.text((235, 42), label, font=_font(39), fill=red)
    draw.line((45, 120, width - 45, 120), fill=red, width=3)
    draw.text((48, 138), f"{role}｜电子签署（测试）", font=_font(31), fill=red)
    draw.text((48, 190), "合成资料｜不得用于真实工程", font=_font(25), fill=red)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
