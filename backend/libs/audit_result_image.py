"""把节点审计结果的摘要渲染成图（可能是好几页）：HTML 模板 → PyMuPDF Story（HTML/CSS 排版）→ PNG。

用在 `POST /inspection-services/audit-result-image`：监检助手（skill）把审计结果的摘要发来，服务器画成图送回，
不存储输入也不存储结果。服务器上没有无头浏览器，也不装；PyMuPDF 本来就在，Story 够排这种页面，
中文用它自带的 CJK 字体，所以不依赖宿主机装了什么字体，本机、CI、生产画出来一样。

版面：白底、大字号、宽行距、留白多。第一页是总览（结论、各结论占比、最要先做的事、风险、缺的资料），
逐项结论一项一张卡片。内容一页放不下就分页：每页固定尺寸，页眉页脚带“第 N / 共 M 页”；
**整张卡片不拆开**（Story 不认 page-break-inside，所以分页自己做：先把每个版块单独排一遍量出高度，再按页面容量装页）。

只收摘要：节点结论、每项一句话理由和主要依据、最要先做的事、风险提示。收到什么就画什么，
不替调用方下结论；结论、理由都是调用方给的，这里只做校验、脱敏和排版。

渲染放在子进程里（`render_in_subprocess`）：API 进程已经很大，画图的内存和卡死都不能算在它头上；
子进程有超时和 CPU 上限，输出有大小上限。
"""
from __future__ import annotations

import base64
import html
import io
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_BODY_BYTES = 256 * 1024
MAX_CHECKS = 80
MAX_STEPS = 8
MAX_RISKS = 8
MAX_MATERIALS = 10
MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_PAGES = 16
PAGE_WIDTH_PT, PAGE_HEIGHT_PT = 640, 905  # A4 的比例；一页放不下就分页，每页这个尺寸
MARGIN_LEFT_PT, MARGIN_RIGHT_PT, MARGIN_TOP_PT, MARGIN_BOTTOM_PT = 32, 32, 44, 52  # 上下留给页眉、页脚
CONTENT_PT = PAGE_WIDTH_PT - MARGIN_LEFT_PT - MARGIN_RIGHT_PT
CAPACITY_PT = PAGE_HEIGHT_PT - MARGIN_TOP_PT - MARGIN_BOTTOM_PT
MIN_SINGLE_PAGE_PT = 520  # 只有一页时按内容取高度，但不矮于这个
SUMMARY_BREAK_RATIO = 0.55  # 总览部分占了半页以上，逐项详情就另起一页，免得总览页又挤又被拦腰
DPI = 150
SUBPROCESS_TIMEOUT_SECONDS = 45
PROBE_HEIGHT_PT = 30000  # 量单个版块高度用的高纸

# 白底、一个主色（蓝）、语义色只用在结论上：颜色都写死在这里，调用方给不了颜色。
TEXT, SECOND, MUTED, LINE, PANEL, BRAND = "#101828", "#475467", "#98a2b3", "#eaecf0", "#f9fafb", "#175cd3"
# (文字, 强色, 浅底)
OUTCOMES = {"passed": ("通过", "#027a48", "#ecfdf3"), "failed": ("不通过", "#b42318", "#fef3f2"),
            "pending": ("暂不能判定通过", "#b54708", "#fffaeb")}
VERDICTS = {
    "passed": ("符合", "#027a48", "#ecfdf3"),
    "failed": ("不符合", "#b42318", "#fef3f2"),
    "evidence_insufficient": ("证据不足", "#b54708", "#fffaeb"),
    "human_review_required": ("需人工确认", "#175cd3", "#eff8ff"),
    "not_applicable": ("不适用", "#475467", "#f2f4f7"),
    "not_executed": ("未执行", "#475467", "#f2f4f7"),
}
RISK_LEVELS = {"high": ("高风险", "#b42318", "#fef3f2"), "medium": ("中风险", "#b54708", "#fffaeb")}
# 卡片、色块的宽度必须写成绝对的 pt：PyMuPDF 的 Story 不认百分比和 table-layout，按内容自动分会把小格子挤到只剩两个字宽。
# 写的是内容宽，单元格内边距另算。
CARD_PAD_PT, CARD_BORDER_PT, CARD_ACCENT_PT = 16, 1, 4
CARD_INNER_PT = CONTENT_PT - CARD_BORDER_PT - CARD_ACCENT_PT - 2 * CARD_PAD_PT
CHIP_PT, CHIP_PAD_PT = 74, 6  # 卡片右上角的结论标签
CARD_TITLE_PT = CARD_INNER_PT - CHIP_PT - 2 * CHIP_PAD_PT - 8
STEP_NUMBER_PT = 24
BAR_PT = 4  # 风险、缺资料块左边的色条
TEXT_LIMITS = {"nodeName": 60, "ruleId": 20, "projectLabel": 80, "outcomeExplain": 300, "summary": 600, "auditedAt": 40,
               "auditor": 80, "source": 80, "atomicCheckId": 30, "title": 120, "reason": 400, "evidence": 300,
               "step": 300, "flag": 200, "basis": 200, "material": 200}
ID_NUMBER = re.compile(r"(?<![0-9A-Za-z])(\d{4})\d{10}(\d{3}[\dXx])(?![0-9A-Za-z])")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
CJK_FONT = "china-s"  # PyMuPDF 自带的 CJK 字体，不随宿主机变化
FONT_FACE = "@font-face { font-family: cjk; src: url(cjk.ttf); }"


class AuditImageError(ValueError):
    """调用方给的摘要不合格或内容过长（`client`，对应 400），或渲染没成功（调用方按 `retryable` 决定重试不重试）。"""

    def __init__(self, message: str, *, retryable: bool = False, client: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.client = client


def clean_text(value: Any, limit: int, *, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str | int | float):
        raise AuditImageError(f"{field} 须为文字。")
    text = CONTROL.sub("", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    text = ID_NUMBER.sub(lambda m: f"{m.group(1)}**********{m.group(2)}", text)  # 完整证号不画进图里，调用方漏脱敏也兜住
    return text if len(text) <= limit else text[: limit - 1] + "…"


def clean_list(value: Any, cap: int, limit: int, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AuditImageError(f"{field} 须为数组。")
    items = [clean_text(item, limit, field=field) for item in value[:cap]]
    return [item for item in items if item]


def normalize_summary(payload: Any) -> dict[str, Any]:
    """校验并清洗摘要：类型不对就拒绝，过长的文字截断，证号脱敏，多余的字段忽略。"""
    if not isinstance(payload, dict):
        raise AuditImageError("请求体须为 JSON 对象。")
    outcome = payload.get("outcome")
    if outcome not in OUTCOMES:
        raise AuditImageError(f"outcome 须为 {sorted(OUTCOMES)} 之一。")
    node_id = payload.get("nodeId")
    if type(node_id) is not int or not 1 <= node_id <= 999:
        raise AuditImageError("nodeId 须为 1–999 的整数。")
    checks_in = payload.get("checks")
    if not isinstance(checks_in, list) or not checks_in:
        raise AuditImageError("checks 须为非空数组。")
    if len(checks_in) > MAX_CHECKS:
        raise AuditImageError(f"checks 最多 {MAX_CHECKS} 项。")
    checks = []
    for index, row in enumerate(checks_in, start=1):
        if not isinstance(row, dict):
            raise AuditImageError(f"checks[{index}] 须为对象。")
        if row.get("verdict") not in VERDICTS:
            raise AuditImageError(f"checks[{index}].verdict 须为 {sorted(VERDICTS)} 之一。")
        check_id = clean_text(row.get("atomicCheckId"), TEXT_LIMITS["atomicCheckId"], field="atomicCheckId")
        if not check_id:
            raise AuditImageError(f"checks[{index}].atomicCheckId 不能为空。")
        differs = row.get("differsFromServer")
        checks.append({
            "atomicCheckId": check_id, "title": clean_text(row.get("title"), TEXT_LIMITS["title"], field="title"),
            "verdict": row["verdict"], "reason": clean_text(row.get("reason"), TEXT_LIMITS["reason"], field="reason"),
            "evidence": clean_text(row.get("evidence"), TEXT_LIMITS["evidence"], field="evidence"),
            "differsFromServer": differs if isinstance(differs, bool) else None,
        })
    risks = []
    for row in (payload.get("riskFlags") or [])[:MAX_RISKS] if isinstance(payload.get("riskFlags"), list) else []:
        if isinstance(row, dict) and row.get("level") in RISK_LEVELS and clean_text(row.get("flag"), 1, field="flag"):
            risks.append({"level": row["level"], "flag": clean_text(row.get("flag"), TEXT_LIMITS["flag"], field="flag"),
                          "basis": clean_text(row.get("basis"), TEXT_LIMITS["basis"], field="basis")})
    return {
        "nodeId": node_id, "outcome": outcome,
        **{key: clean_text(payload.get(key), TEXT_LIMITS[key], field=key)
           for key in ("nodeName", "ruleId", "projectLabel", "outcomeExplain", "summary", "auditedAt", "auditor", "source")},
        "checks": checks,
        "nextSteps": clean_list(payload.get("nextSteps"), MAX_STEPS, TEXT_LIMITS["step"], field="nextSteps"),
        "missingMaterials": clean_list(payload.get("missingMaterials"), MAX_MATERIALS, TEXT_LIMITS["material"], field="missingMaterials"),
        "riskFlags": risks,
    }


def esc(text: str) -> str:
    """模板里的每一段文字都过这里：调用方给的内容不能变成标签。"""
    return html.escape(text, quote=True)


def stylesheet() -> str:
    chips = "\n".join(f"td.v-{key} {{ background-color: {soft}; color: {strong}; text-align: center; font-size: 11px; "
                      f"padding: 4px {CHIP_PAD_PT}px 4px {CHIP_PAD_PT}px; }}" for key, (_, strong, soft) in VERDICTS.items())
    return f"""
body {{ font-family: cjk; font-size: 12px; color: {TEXT}; line-height: 1.6; margin: 0; }}
table {{ border-collapse: collapse; }}
.eyebrow {{ color: {MUTED}; font-size: 10.5px; margin: 0; }}
h1 {{ font-size: 23px; color: {TEXT}; margin: 3px 0 0 0; }}
.sub {{ font-family: monospace; color: {SECOND}; font-size: 11px; margin: 2px 0 0 0; }}
.label {{ color: {SECOND}; font-size: 10.5px; margin: 0; }}
.explain {{ color: {SECOND}; font-size: 12px; margin: 4px 0 0 0; }}
table.seg td {{ padding: 4px 0 4px 0; font-size: 1px; }}
table.legend td {{ font-size: 11px; text-align: center; padding: 3px 8px 3px 8px; }}
.meta {{ color: {MUTED}; font-size: 10.5px; margin: 10px 0 0 0; }}
h2 {{ font-size: 16px; color: {TEXT}; margin: 0 0 10px 0; padding-bottom: 6px; border-bottom: 1px solid {LINE}; }}
.card {{ border: {CARD_BORDER_PT}px solid {LINE}; padding: 11px {CARD_PAD_PT}px 11px {CARD_PAD_PT}px; }}
.id {{ font-family: monospace; font-size: 10px; color: {SECOND}; }}
.ctitle {{ font-size: 13.5px; color: {TEXT}; }}
{chips}
.reason {{ margin: 6px 0 0 0; }}
.warn {{ color: #b54708; font-size: 10.5px; margin: 4px 0 0 0; }}
.ev {{ color: {SECOND}; font-size: 11px; margin: 6px 0 0 0; }}
.evl {{ color: {MUTED}; font-size: 9.5px; }}
table.step td {{ vertical-align: top; padding: 0; }}
td.n {{ background-color: {BRAND}; color: #ffffff; text-align: center; font-family: monospace; padding: 2px 0 2px 0; }}
span.sid {{ font-family: monospace; color: {BRAND}; font-size: 10.5px; }}
.risk {{ padding: 10px 14px 10px 14px; }}
.rtag {{ font-size: 10.5px; }}
.muted {{ color: {MUTED}; font-size: 10.5px; }}
table.item td {{ vertical-align: top; padding: 0; }}
.summary {{ background-color: {PANEL}; border-left: 4px solid {BRAND}; padding: 12px 16px 12px 16px; margin: 0; }}
"""


def lines(text: str) -> str:
    """依据里一处一行：`甲.pdf 第1页；乙.pdf 第3页 等 8 处` 比挤在一行好读。"""
    return "<br>".join(esc(part.strip()) for part in re.split(r"[；;]", text) if part.strip()) or "—"


def segment_widths(counts: dict[str, int], total_pt: int) -> list[tuple[str, int]]:
    """分段条：每种结论按占比分宽度，加起来刚好等于总宽；有的结论至少留 3pt，免得一项也看不见。"""
    present = [(v, counts[v]) for v in VERDICTS if counts.get(v)]
    count = sum(n for _, n in present) or 1
    widths = [max(3, total_pt * n // count) for _, n in present]
    widths[widths.index(max(widths))] += total_pt - sum(widths)
    return [(v, w) for (v, _), w in zip(present, widths, strict=True)]


def gap(points: int) -> str:
    """版块之间的间隔：用内边距而不是外边距，外边距会合并，量出来的高度和实际排版对不上。"""
    return f'<div style="font-size: 1px; line-height: 1px; height: {points}px">&nbsp;</div>'


def hero_unit(summary: dict[str, Any]) -> str:
    """总览顶部：节点名、大号结论、各结论占比的分段条、图例、元信息。"""
    label, strong, soft = OUTCOMES[summary["outcome"]]
    counts: dict[str, int] = {}
    for check in summary["checks"]:
        counts[check["verdict"]] = counts.get(check["verdict"], 0) + 1
    meta = "　·　".join(part for part in (
        f"审计时间 {summary['auditedAt']}" if summary["auditedAt"] else "", f"审计者 {summary['auditor']}" if summary["auditor"] else "",
        f"资料来源 {summary['source']}" if summary["source"] else "") if part)
    eyebrow = "　·　".join(part for part in ("节点审计结果", summary["projectLabel"]) if part)
    sub = "　·　".join(part for part in (f"节点 {summary['nodeId']:02d}", summary["ruleId"]) if part)
    title = summary["nodeName"] or f"节点 {summary['nodeId']:02d}"
    segments = "".join(f'<td style="width: {w}pt; background-color: {VERDICTS[v][1]}">&nbsp;</td>'
                       for v, w in segment_widths(counts, CONTENT_PT))
    legend = '<td style="width: 8pt; padding: 0">&nbsp;</td>'.join(
        f'<td class="v-{v}" style="width: {10 * len(VERDICTS[v][0]) + 26}pt">{esc(VERDICTS[v][0])}　{counts[v]}</td>'
        for v in VERDICTS if counts.get(v))
    return (
        f'<p class="eyebrow">{esc(eyebrow)}</p><h1>{esc(title)}</h1>'
        f'<p class="sub">{esc(sub)}</p>{gap(12)}'
        f'<div style="background-color: {soft}; border-left: 6px solid {strong}; padding: 12px 20px 12px 20px">'
        f'<p class="label">审计结论</p><p style="font-size: 28px; line-height: 1.25; color: {strong}; margin: 2px 0 0 0">{esc(label)}</p>'
        + (f'<p class="explain">{esc(summary["outcomeExplain"])}</p>' if summary["outcomeExplain"] else "")
        + f'</div>{gap(12)}<p class="label">共 {len(summary["checks"])} 项检查</p>'
        f'<table class="seg"><tr>{segments}</tr></table>{gap(4)}<table class="legend"><tr>{legend}</tr></table>'
        + (f'<p class="meta">{esc(meta)}</p>' if meta else "") + gap(18))


def heading_unit(title: str) -> str:
    return f"<h2>{esc(title)}</h2>"


STEP_TAG_RE = re.compile(r"(AC-[A-Za-z0-9]+-\d+)\s*[：:]\s*(.+)")
STEP_TAG_PT = 66


def step_unit(number: int, step: str, tagged: bool = False) -> str:
    """tagged：这一组建议里有带检查号的。检查号单独占一列，没有检查号的那几条留空，正文才对得齐。"""
    match = STEP_TAG_RE.match(step)
    text = esc(match.group(2)) if match else esc(step)
    tag_cell = f'<td style="width: {STEP_TAG_PT}pt"><span class="sid">{esc(match.group(1)) if match else "&nbsp;"}</span></td>' if tagged else ""
    text_pt = CONTENT_PT - STEP_NUMBER_PT - 12 - (STEP_TAG_PT if tagged else 0)
    return (f'<table class="step"><tr><td class="n" style="width: {STEP_NUMBER_PT}pt">{number}</td>'
            f'<td style="width: 12pt">&nbsp;</td>{tag_cell}<td style="width: {text_pt}pt">{text}</td></tr></table>{gap(9)}')


def risk_unit(risk: dict[str, str]) -> str:
    tag, strong, soft = RISK_LEVELS[risk["level"]]
    basis = f'<p class="muted" style="margin: 3px 0 0 0">{esc(risk["basis"])}</p>' if risk["basis"] else ""
    return (f'<div class="risk" style="background-color: {soft}; border-left: {BAR_PT}px solid {strong}">'
            f'<span class="rtag" style="color: {strong}">{tag}</span>　{esc(risk["flag"])}{basis}</div>{gap(10)}')


def material_unit(item: str) -> str:
    return (f'<table class="item"><tr><td style="width: 14pt; color: {MUTED}">•</td>'
            f'<td style="width: {CONTENT_PT - 14}pt">{esc(item)}</td></tr></table>{gap(6)}')


def card_unit(check: dict[str, Any]) -> str:
    label, strong, _ = VERDICTS[check["verdict"]]
    title = f'<br><span class="ctitle">{esc(check["title"])}</span>' if check["title"] else ""
    differs = '<p class="warn">与服务器结论不同</p>' if check["differsFromServer"] else ""
    evidence = f'<p class="ev"><span class="evl">依据</span><br>{lines(check["evidence"])}</p>' if check["evidence"] else ""
    return (f'<div class="card" style="border-left: {CARD_ACCENT_PT}px solid {strong}">'
            f'<table><tr><td style="width: {CARD_TITLE_PT}pt; padding: 0"><span class="id">{esc(check["atomicCheckId"])}</span>{title}</td>'
            f'<td style="width: 8pt; padding: 0">&nbsp;</td>'
            f'<td style="width: {CHIP_PT + 2 * CHIP_PAD_PT}pt; padding: 0; vertical-align: top"><table><tr>'
            f'<td class="v-{check["verdict"]}" style="width: {CHIP_PT}pt">{esc(label)}</td></tr></table></td></tr></table>'
            f'<p class="reason">{esc(check["reason"] or "—")}</p>{differs}{evidence}</div>{gap(10)}')


def build_units(summary: dict[str, Any]) -> list[tuple[str, str]]:
    """摘要 → 按顺序排好的版块 [(类型, HTML)]。类型：front 总览部分（结论、建议、风险、缺的资料、总体意见），
    detail 逐项卡片。标题和它后面的第一块合成一个版块，免得标题孤零零留在页底。"""
    units: list[tuple[str, str]] = [("front", hero_unit(summary))]
    for kind, title, items in (("front", "最需要先做的事", [step_unit(n, step, tagged=any(STEP_TAG_RE.match(x) for x in summary["nextSteps"])) for n, step in enumerate(summary["nextSteps"], start=1)]),
                               ("front", "风险提示", [risk_unit(r) for r in summary["riskFlags"]]),
                               ("front", "需要补充的资料", [material_unit(m) for m in summary["missingMaterials"]])):
        for index, item in enumerate(items):
            units.append((kind, (heading_unit(title) if index == 0 else "") + item))
        if items:
            units[-1] = (kind, units[-1][1] + gap(10))
    if summary["summary"]:
        units.append(("front", heading_unit("总体意见") + f'<p class="summary">{esc(summary["summary"])}</p>' + gap(10)))
    cards = [card_unit(check) for check in summary["checks"]]
    return units + [("detail", (heading_unit("逐项结论") if index == 0 else "") + card) for index, card in enumerate(cards)]


def build_html(summary: dict[str, Any]) -> str:
    """整份摘要的 HTML（不分页，给测试和调试用）；实际渲染按版块分页，见 render_summary_pdf。"""
    return f"<style>{stylesheet()}</style>" + "".join(unit for _, unit in build_units(summary))


def rgb(hex_color: str) -> tuple[float, float, float]:
    return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


def layout_story(fitz: Any, archive: Any, units_html: str) -> Any:
    return fitz.Story(html=f"<style>{stylesheet()}</style>{units_html}", user_css=FONT_FACE, archive=archive)


def measure(fitz: Any, archive: Any, units_html: str) -> float:
    """一个版块单独排一遍，量出它占多高。"""
    more, filled = layout_story(fitz, archive, units_html).place(fitz.Rect(0, 0, CONTENT_PT, PROBE_HEIGHT_PT))
    if more:
        raise AuditImageError("内容过长，画不下。")
    return float(filled[3])


def paginate(units: list[tuple[str, str]], heights: list[float]) -> list[list[int]]:
    """把版块按页面容量装进各页，整个版块不拆开。总览部分能完整放进第一页、又占了半页以上，逐项详情就另起一页，
    让第一页是干净的总览；总览自己就溢出到第二页了，详情紧接着排，不再空出半页。"""
    capacity = CAPACITY_PT
    if any(height > capacity for height in heights):
        raise AuditImageError("有一项内容太长，一页放不下。")
    front = sum(h for (kind, _), h in zip(units, heights, strict=True) if kind == "front")
    force_break = sum(heights) > capacity and capacity * SUMMARY_BREAK_RATIO < front <= capacity
    pages: list[list[int]] = [[]]
    used = 0.0
    for index, ((kind, _), height) in enumerate(zip(units, heights, strict=True)):
        starts_details = kind == "detail" and (index == 0 or units[index - 1][0] != "detail")
        if pages[-1] and (used + height > capacity or (force_break and starts_details)):
            pages.append([])
            used = 0.0
        pages[-1].append(index)
        used += height
    return pages


def render_summary_pdf(summary: dict[str, Any]) -> bytes:
    """排成一份 PDF：一页放得下就是一页（高度按内容取），放不下就分页，每页固定尺寸、整个版块不拆开，
    页眉页脚带“第 N / 共 M 页”。"""
    import fitz  # PyMuPDF，延迟导入：API 进程不需要为校验付这个代价

    archive = fitz.Archive()
    archive.add(fitz.Font(CJK_FONT).buffer, "cjk.ttf")
    units = build_units(summary)
    heights = [measure(fitz, archive, html_text) for _, html_text in units]
    pages = paginate(units, heights)
    if len(pages) > MAX_PAGES:
        raise AuditImageError(f"内容过长：超过 {MAX_PAGES} 页。")
    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    for number, members in enumerate(pages):
        page_height = PAGE_HEIGHT_PT
        if len(pages) == 1:
            page_height = max(MIN_SINGLE_PAGE_PT, math.ceil(sum(heights)) + MARGIN_TOP_PT + MARGIN_BOTTOM_PT + 2)
        device = writer.begin_page(fitz.Rect(0, 0, PAGE_WIDTH_PT, page_height))
        story = layout_story(fitz, archive, "".join(units[i][1] for i in members))
        # 排版区一直到页底（下边距当余量）：单独量出的高度和合在一起排的高度可能差不到 1pt，
        # 放不下的最后一段会被挤出页面而没人发现；放不下就报错，绝不静默丢内容。
        still_more, _ = story.place(fitz.Rect(MARGIN_LEFT_PT, MARGIN_TOP_PT, PAGE_WIDTH_PT - MARGIN_RIGHT_PT, page_height - MARGIN_BOTTOM_PT + 8))
        if still_more:
            raise AuditImageError("内容排不进一页。")
        story.draw(device)
        writer.end_page()
    writer.close()
    with fitz.open("pdf", buffer.getvalue()) as document:
        for number, page in enumerate(document):
            decorate_page(page, summary, number + 1, document.page_count, archive)
        return document.tobytes()


def decorate_page(page: Any, summary: dict[str, Any], number: int, total: int, archive: Any) -> None:
    """页顶一条结论颜色的细线；第 2 页起有页眉；每页页脚有免责说明和页码。
    字用 insert_htmlbox 画（和正文同一套排版和字体）：用 insert_text 配自带 CJK 字体画，拉丁字符和数字会被撑宽，
    出来是“节点 2 4”“A I”。"""
    import fitz

    rect = page.rect
    page.draw_rect(fitz.Rect(0, 0, rect.width, 4), color=None, fill=rgb(OUTCOMES[summary["outcome"]][1]))
    css = FONT_FACE + f" body {{ font-family: cjk; font-size: 9.5px; color: {MUTED}; margin: 0; }}"
    if number > 1:
        head = f"节点 {summary['nodeId']:02d}" + (f" {summary['nodeName']}" if summary["nodeName"] else "") + "　·　节点审计结果"
        page.insert_htmlbox(fitz.Rect(MARGIN_LEFT_PT, 14, rect.width - MARGIN_RIGHT_PT, 34), f"<p>{esc(head)}</p>", css=css, archive=archive)
    line_y = rect.height - 36
    page.draw_line((MARGIN_LEFT_PT, line_y), (rect.width - MARGIN_RIGHT_PT, line_y), color=rgb(LINE), width=0.8)
    # 左右各一个框：放在同一个表格里，右边的页码最后一个字会被切掉
    page.insert_htmlbox(fitz.Rect(MARGIN_LEFT_PT, line_y + 6, MARGIN_LEFT_PT + 380, line_y + 26),
                        "<p>AI 辅助审计意见，不代替监检人员的正式结论</p>", css=css, archive=archive)
    page.insert_htmlbox(fitz.Rect(rect.width - MARGIN_RIGHT_PT - 140, line_y + 6, rect.width - MARGIN_RIGHT_PT - 4, line_y + 26),
                        f'<p style="text-align: right">第 {number} / {total} 页</p>', css=css, archive=archive)


def render_summary_pngs(summary: dict[str, Any]) -> list[bytes]:
    import fitz

    pages = []
    with fitz.open("pdf", render_summary_pdf(summary)) as document:
        for page in document:
            png = page.get_pixmap(dpi=DPI).tobytes("png")
            if len(png) > MAX_PNG_BYTES:
                raise AuditImageError("结果图过大。")
            pages.append(png)
    return pages


def render_in_subprocess(summary: dict[str, Any], *, timeout: float = SUBPROCESS_TIMEOUT_SECONDS) -> list[bytes]:
    """在隔离的子进程里画（`-I`：不读环境变量和当前目录，脚本只用标准库加 PyMuPDF）。
    CPU 上限由子进程启动时自己设（见 main）：API 是多线程进程，用 preexec_fn 设有死锁风险。"""
    try:
        done = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve())],
            input=json.dumps(summary, ensure_ascii=False).encode("utf-8"), capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise AuditImageError("渲染超时。", retryable=True) from None
    except OSError:
        raise AuditImageError("渲染进程启动失败。", retryable=True) from None
    if done.returncode != 0:
        message = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["渲染失败。"]
        # 退出码 2 是 AuditImageError（摘要不合格、内容过长，调用方可以自己处理），3 是画图本身出了问题
        raise AuditImageError(message[0][:200], retryable=False, client=done.returncode == 2)
    try:
        pages = [base64.b64decode(item, validate=True) for item in json.loads(done.stdout)["pages"]]
    except (ValueError, KeyError, TypeError):
        raise AuditImageError("渲染结果格式不对。") from None
    if not pages or not all(page.startswith(b"\x89PNG") for page in pages):
        raise AuditImageError("渲染没有产出图片。")
    return pages


def main() -> int:
    """子进程入口：stdin 读摘要 JSON，stdout 写 {"pages": [每页 PNG 的 base64]}。出错写 stderr 最后一行，非 0 退出。"""
    try:
        import resource

        limit = int(SUBPROCESS_TIMEOUT_SECONDS) + 5  # 比父进程的超时多一点：正常情况下先超时被杀，这是兜底
        resource.setrlimit(resource.RLIMIT_CPU, (limit, limit))
    except (ImportError, ValueError, OSError):
        pass  # 非 POSIX：只靠父进程的超时
    try:
        pages = render_summary_pngs(normalize_summary(json.loads(sys.stdin.buffer.read())))
    except AuditImageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 -- 子进程最外层：任何失败都要变成一行说明和非 0 退出码
        print(f"渲染失败：{type(exc).__name__}", file=sys.stderr)
        return 3
    sys.stdout.write(json.dumps({"pages": [base64.b64encode(page).decode("ascii") for page in pages]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
