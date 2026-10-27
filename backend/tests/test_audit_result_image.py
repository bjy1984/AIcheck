"""节点审计结果图（HTML 模板 → 白底多页 PNG）：输入校验与脱敏、模板转义、分页（整张卡片不拆开）、
画出来的图、接口的鉴权/限流/不存储。

画图用 PyMuPDF 自带的 CJK 字体，不依赖宿主机装了什么字体，所以这些测试在本机、CI、生产容器里结果一样。
"""
from __future__ import annotations

import base64
import io
import math
import re
import subprocess
from collections import Counter

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from apps.api import audit_result_image_routes as routes
from apps.api import main
from libs import audit_result_image as ari
from libs.db.repository import repo

client = TestClient(main.app)
URL = "/api/inspection-services/audit-result-image"
INSPECTION = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
FULL_ID, MASKED_ID = "110101199001011237", "1101**********1237"
PAGE_PX = (math.ceil(ari.PAGE_WIDTH_PT * ari.DPI / 72), math.ceil(ari.PAGE_HEIGHT_PT * ari.DPI / 72))  # 位图尺寸向上取整


def check(i: int = 1, verdict: str = "passed", **extra) -> dict:
    return {"atomicCheckId": f"AC-R24-{i:02d}", "title": "证书有效性", "verdict": verdict,
            "reason": "焊工证在施焊期内有效。", "evidence": "焊工证.pdf 第1、5页", **extra}


def summary(checks: list[dict] | None = None, **extra) -> dict:
    return {"nodeId": 24, "nodeName": "焊工资格", "ruleId": "R24", "outcome": "pending",
            "outcomeExplain": "还有检查项缺证据。", "auditedAt": "2026-10-27 20:50", "auditor": "测试助手",
            "checks": checks if checks is not None else [check(1), check(2, "failed"), check(3, "evidence_insufficient"),
                                                         check(4, "human_review_required")],
            "nextSteps": ["请施工方补实际施焊记录。"], **extra}


def short(**extra) -> dict:
    """一页放得下的结果。"""
    return summary(checks=[check(1), check(2, "failed")], **extra)


def long(count: int = 30, **extra) -> dict:
    return summary(checks=[check(i, ["passed", "failed", "evidence_insufficient", "human_review_required"][i % 4],
                                 reason="理由说明。" * (i % 6 + 1)) for i in range(1, count + 1)], **extra)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    repo.reset()
    monkeypatch.setattr(repo, "postgres_enabled", False)
    monkeypatch.setattr(repo, "sync_postgres", None)
    monkeypatch.setattr(repo, "postgres_dsn", None)
    monkeypatch.setattr(repo, "sqlite_enabled", False)
    monkeypatch.setattr(repo, "sqlite_path", None)


def decode(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def near(pixel: tuple[int, int, int], hex_color: str, tolerance: int = 12) -> bool:
    target = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return all(abs(a - b) <= tolerance for a, b in zip(pixel, target, strict=True))


def page_texts(payload: dict) -> list[str]:
    with fitz.open("pdf", ari.render_summary_pdf(ari.normalize_summary(payload))) as document:
        return [page.get_text() for page in document]


def page_lines(payload: dict) -> list[str]:
    """每一行文字（折行后各是一行），所有页合在一起。"""
    with fitz.open("pdf", ari.render_summary_pdf(ari.normalize_summary(payload))) as document:
        return ["".join(span["text"] for span in line["spans"]) for page in document for block in page.get_text("dict")["blocks"]
                for line in block.get("lines", [])]


# ---------------------------------------------------------------- 校验与清洗

def test_a_bad_summary_is_rejected_with_a_message_that_says_what_is_wrong():
    for payload, fragment in (
        ([], "JSON 对象"), (summary(outcome="maybe"), "outcome"), ({**summary(), "nodeId": "24"}, "nodeId"),
        ({**summary(), "nodeId": 0}, "nodeId"), (summary(checks=[]), "checks"),
        (summary(checks=[check(verdict="great")]), "verdict"), (summary(checks=["x"]), "checks[1]"),
        (summary(checks=[check() for _ in range(ari.MAX_CHECKS + 1)]), "最多"),
        (summary(checks=[{**check(), "atomicCheckId": " "}]), "atomicCheckId"),
        ({**summary(), "nextSteps": "not a list"}, "nextSteps"),
    ):
        with pytest.raises(ari.AuditImageError, match=re.escape(fragment)):
            ari.normalize_summary(payload)


def test_text_is_cleaned_truncated_and_full_id_numbers_are_masked():
    big = "很长" * 500
    out = ari.normalize_summary(summary(
        checks=[check(reason=f"证号 {FULL_ID}\x00\x07 换行\n\n多空格   结束", evidence=big)],
        nextSteps=[big] * 20, unknownField="被忽略", summary=f"总体 {FULL_ID}"))
    row = out["checks"][0]
    assert MASKED_ID in row["reason"] and FULL_ID not in row["reason"]  # 调用方漏脱敏，这里兜住
    assert "\x00" not in row["reason"] and "\n" not in row["reason"] and "多空格 结束" in row["reason"]
    assert len(row["evidence"]) == ari.TEXT_LIMITS["evidence"] and row["evidence"].endswith("…")
    assert len(out["nextSteps"]) == ari.MAX_STEPS and "unknownField" not in out
    assert FULL_ID not in out["summary"]


def test_every_caller_supplied_string_is_escaped_in_the_html():
    attack = '<script>alert(1)</script><b onclick="x">&</b>'
    html_text = ari.build_html(ari.normalize_summary(summary(
        nodeName=attack, projectLabel=attack, checks=[check(reason=attack, evidence=attack, title=attack)],
        nextSteps=[attack], missingMaterials=[attack], riskFlags=[{"level": "high", "flag": attack, "basis": attack}],
        outcomeExplain=attack, summary=attack)))
    assert "<script" not in html_text and "<b onclick" not in html_text
    assert html_text.count("&lt;script&gt;") >= 10  # 每个位置都转义了


def test_the_hero_colours_follow_the_overall_outcome():
    for outcome, (label, strong, soft) in ari.OUTCOMES.items():
        html_text = ari.build_html(ari.normalize_summary(summary(outcome=outcome)))
        assert f"border-left: 6px solid {strong}" in html_text and f"background-color: {soft}" in html_text and label in html_text


def test_the_segment_bar_splits_the_width_by_count_and_always_adds_up():
    widths = dict(ari.segment_widths({"passed": 2, "evidence_insufficient": 2, "human_review_required": 1}, ari.CONTENT_PT))
    assert sum(widths.values()) == ari.CONTENT_PT  # 取整的零头摊进去，总宽一点不差
    assert abs(widths["passed"] - widths["evidence_insufficient"]) <= 1 and abs(widths["passed"] - 2 * widths["human_review_required"]) <= 2
    for counts in ({"failed": 1}, {"passed": 99, "failed": 1}, {v: 1 for v in ari.VERDICTS}, {"passed": 7, "failed": 3, "not_executed": 1}):
        total = ari.segment_widths(counts, ari.CONTENT_PT)
        assert sum(w for _, w in total) == ari.CONTENT_PT and all(w >= 3 for _, w in total), counts  # 再少的结论也看得见


# ---------------------------------------------------------------- 分页

def test_blocks_are_packed_into_pages_without_ever_splitting_one():
    cap = ari.CAPACITY_PT
    u = lambda kind, n: [(kind, "") for _ in range(n)]
    # 全放得下：一页
    assert ari.paginate(u("front", 2) + u("detail", 2), [100, 100, 100, 100]) == [[0, 1, 2, 3]]
    # 总览放得下第一页、占了大半：详情另起一页，第一页是干净的总览
    assert ari.paginate(u("front", 2) + u("detail", 3), [350, 300, 150, 150, 150]) == [[0, 1], [2, 3, 4]]
    # 总览很小：详情紧接着排，不留空
    assert ari.paginate(u("front", 1) + u("detail", 5), [200, 150, 150, 150, 150, 150]) == [[0, 1, 2, 3, 4], [5]]
    # 总览自己溢出到第二页：详情紧接在后面，不再空出半页
    pages = ari.paginate(u("front", 2) + u("detail", 2), [cap * 0.6, cap * 0.6, 150, 150])
    assert pages == [[0], [1, 2, 3]]
    # 一个版块自己就比一页高：报错，不截断
    with pytest.raises(ari.AuditImageError, match="一页放不下"):
        ari.paginate(u("detail", 1), [cap + 1])


def test_a_short_result_is_one_page_cropped_to_its_content():
    pages = ari.render_summary_pngs(ari.normalize_summary(short()))
    assert len(pages) == 1
    image = decode(pages[0])
    assert image.width == PAGE_PX[0] and round(ari.MIN_SINGLE_PAGE_PT * ari.DPI / 72) <= image.height < PAGE_PX[1]
    texts = page_texts(short())
    assert len(texts) == 1 and "第 1 / 1 页" in texts[0] and "审计结论" in texts[0]


def test_a_long_result_is_split_into_equal_pages_with_running_header_and_page_numbers():
    payload = long(30)
    pngs = ari.render_summary_pngs(ari.normalize_summary(payload))
    texts = page_texts(payload)
    assert len(pngs) == len(texts) > 2
    assert {decode(png).size for png in pngs} == {PAGE_PX}  # 每页同样大
    for number, text in enumerate(texts, start=1):
        assert f"第 {number} / {len(texts)} 页" in text and "AI 辅助审计意见" in text  # 每页有页码和免责说明
        assert ("节点 24 焊工资格" in text and "节点审计结果" in text) == (number > 1)  # 第 2 页起有页眉
    assert "审计结论" in texts[0] and "审计结论" not in "".join(texts[1:])


def test_no_check_card_is_ever_split_across_pages():
    """回归：Story 不认 page-break-inside，卡片会被拦腰截断：编号在上一页，它的依据掉到下一页。"""
    for count in (1, 2, 3, 5, 8, 13, 21, 40):
        payload = long(count)
        texts = page_texts(payload)
        ids = [re.findall(r"AC-R24-\d\d", text) for text in texts]
        assert sum(len(x) for x in ids) == count and len({i for x in ids for i in x}) == count, count  # 每项恰好出现一次
        for number, (text, on_page) in enumerate(zip(texts, ids, strict=True), start=1):
            assert text.count("依据") == len(on_page), (count, number)  # 这页的卡片，每张都带着自己的依据，没有孤零零的依据
        flat = [i for x in ids for i in x]
        assert flat == sorted(flat), count  # 顺序没乱


def test_the_details_start_on_a_new_page_only_when_that_keeps_page_one_a_clean_summary():
    steps = ["请施工方补实际施焊记录。" * 6] * 6
    texts = page_texts(summary(checks=[check(1), check(2, "failed"), check(3), check(4)], nextSteps=steps,
                               riskFlags=[{"level": "high", "flag": "风险" * 20}], missingMaterials=["缺" * 40]))
    assert "逐项结论" not in texts[0] and "逐项结论" in texts[1]  # 总览占了大半：详情另起一页


def test_the_last_paragraph_is_never_silently_dropped_whatever_the_length():
    """回归：第二次排版的区域只比内容多不到 1pt，取整后放不下，页脚被挤出页面，图里少了一段却没人发现。"""
    for count in (1, 2, 3, 5, 8, 13, 21, 40):
        payload = long(count, nextSteps=["建议" * i for i in range(1, count % 5 + 2)], missingMaterials=["缺" * 9] * (count % 3),
                       riskFlags=[{"level": "medium", "flag": "风险" * 5}] * (count % 2), summary="总体意见" * count)
        texts = page_texts(payload)
        assert f"AC-R24-{count:02d}" in "".join(texts), count  # 最后一项检查还在
        assert "总体意见" in texts[0] + (texts[1] if len(texts) > 1 else ""), count  # 总体意见在总览里
        assert all(f"第 {n} / {len(texts)} 页" in text for n, text in enumerate(texts, start=1)), count  # 每页的页脚都在


def test_content_that_cannot_fit_is_an_error_not_a_cropped_image(monkeypatch):
    real_place = fitz.Story.place

    def squeeze(self, rect, *args, **kwargs):  # 真正画一页的那次排版（区域从上页边距开始）假装放不下
        more, filled = real_place(self, rect, *args, **kwargs)
        return (True, filled) if rect.y0 == ari.MARGIN_TOP_PT else (more, filled)

    monkeypatch.setattr(fitz.Story, "place", squeeze)
    with pytest.raises(ari.AuditImageError, match="排不进一页"):
        ari.render_summary_pdf(ari.normalize_summary(short()))


def test_too_many_pages_is_a_client_error(monkeypatch):
    monkeypatch.setattr(ari, "MAX_PAGES", 2)
    with pytest.raises(ari.AuditImageError, match="过长") as caught:
        ari.render_summary_pdf(ari.normalize_summary(long(30)))
    assert caught.value.client is False  # 渲染层的限制；到路由时由 render_in_subprocess 按退出码标成客户端错误


# ---------------------------------------------------------------- 画出来的图

def test_the_png_is_a_white_page_with_the_outcome_colour_verdict_colours_and_chinese_text():
    payload = ari.normalize_summary(summary())
    image = decode(ari.render_summary_pngs(payload)[0])
    colors = Counter(image.getdata())
    assert near(max(colors, key=colors.get), "#ffffff", 4)  # 白底
    assert near(image.getpixel((image.width // 2, 2)), ari.OUTCOMES["pending"][1], 12)  # 页顶一条结论颜色的细线
    assert sum(n for c, n in colors.items() if near(c, ari.OUTCOMES["pending"][2], 3)) > 3000  # 结论块的浅底
    for verdict in ("passed", "failed", "evidence_insufficient", "human_review_required"):
        assert sum(n for c, n in colors.items() if near(c, ari.VERDICTS[verdict][1], 6)) > 300, verdict  # 分段条里有这种结论的色段
    texts = page_texts(summary())
    joined = "".join(texts)
    assert "暂不能判定通过" in joined and "焊工证在施焊期内有效。" in joined and "请施工方补实际施焊记录。" in joined
    with fitz.open("pdf", ari.render_summary_pdf(payload)) as document:
        assert document[0].get_fonts()  # 字体真的嵌进去了
    dark = sum(1 for r, g, b in image.getdata() if max(r, g, b) < 90)
    assert dark > 2000  # 正文是深色字


def test_nothing_is_drawn_outside_the_page_margins_even_with_long_cells():
    """回归：内容超出右页边距会被切掉最后一个字。左右页边距里除了顶部的细线、页脚的线和页码，必须是空白。"""
    wide = long(6, nextSteps=["很长的建议，" * 30], missingMaterials=["很长的资料说明，" * 20],
                riskFlags=[{"level": "high", "flag": "很长的风险，" * 25, "basis": "依据，" * 30}])
    wide["checks"][0].update(reason="很长的理由，" * 60, evidence="标准 TSGZ6002-2010《焊接人员考核细则》 第30页；" * 3)
    margin_px = round(ari.MARGIN_LEFT_PT * ari.DPI / 72)
    for png in ari.render_summary_pngs(ari.normalize_summary(wide)):
        image = decode(png)
        for y in range(12, image.height - 90, 2):  # 去掉顶部细线和页脚
            for x in list(range(margin_px - 8)) + list(range(image.width - margin_px + 8, image.width)):
                assert min(image.getpixel((x, y))) >= 240, (x, y)


def test_the_verdict_labels_and_legend_chips_are_never_wrapped():
    """回归：Story 不认列宽百分比，色块被挤到只剩两个字宽，「需人工确认」折成几行。"""
    lines = page_lines(long(12, ))
    for label in ("需人工确认", "证据不足", "符合", "不符合"):
        assert label in lines, (label, [line for line in lines if label[0] in line][:4])  # 卡片右上角的标签
    assert any(re.fullmatch(r"需人工确认　\d+", line) for line in lines)  # 总览里的图例色块


def test_evidence_goes_on_one_line_per_place_and_steps_carry_a_check_tag():
    html_text = ari.build_html(ari.normalize_summary(summary(
        checks=[check(evidence="甲.pdf 第1页；乙.pdf 第3页；丙.pdf 第5页 等 9 处")],
        nextSteps=["AC-R24-03：请施工方补记录", "没有检查号的建议"])))
    assert html_text.count("甲.pdf 第1页<br>乙.pdf 第3页<br>丙.pdf 第5页 等 9 处") == 1
    assert '<span class="sid">AC-R24-03</span>' in html_text and "没有检查号的建议" in html_text
    # 一组建议里有的带检查号、有的不带：检查号单独占一列，不带的留空，正文才对得齐
    assert html_text.count(f'<td style="width: {ari.STEP_TAG_PT}pt">') == 2 and '<span class="sid">&nbsp;</span>' in html_text
    untagged = ari.build_html(ari.normalize_summary(summary(nextSteps=["甲建议", "乙建议"])))
    assert f'<td style="width: {ari.STEP_TAG_PT}pt">' not in untagged  # 全都没有检查号就不留这一列


def test_the_subprocess_renders_real_pages_and_a_timeout_is_a_retryable_error(monkeypatch):
    pages = ari.render_in_subprocess(ari.normalize_summary(long(12)))
    assert len(pages) > 1 and all(page.startswith(b"\x89PNG") for page in pages) and {decode(p).size for p in pages} == {PAGE_PX}

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="render", timeout=1)

    monkeypatch.setattr(ari.subprocess, "run", hang)
    with pytest.raises(ari.AuditImageError) as caught:
        ari.render_in_subprocess(ari.normalize_summary(short()), timeout=1)
    assert caught.value.retryable is True and caught.value.client is False


def test_the_subprocess_reports_bad_input_on_one_line_and_marks_it_as_the_callers_problem(monkeypatch):
    done = subprocess.run([ari.sys.executable, "-I", ari.__file__], input=b'{"outcome": "nope"}', capture_output=True, check=False)
    assert done.returncode == 2 and done.stdout == b"" and b"Traceback" not in done.stderr and "outcome" in done.stderr.decode("utf-8")
    real_run = subprocess.run
    monkeypatch.setattr(ari.subprocess, "run", lambda *a, **k: real_run(a[0], input=b'{"outcome": "nope"}', capture_output=True, check=False))
    with pytest.raises(ari.AuditImageError) as caught:
        ari.render_in_subprocess(ari.normalize_summary(short()))
    assert caught.value.client is True  # 退出码 2：摘要不合格或内容过长，调用方自己能处理


# ---------------------------------------------------------------- 接口

def pages_of(response) -> list[bytes]:
    data = response.json()["data"]
    assert data["pageCount"] == len(data["pages"]) and data["contentType"] == "image/png"
    assert [p["pageNo"] for p in data["pages"]] == list(range(1, data["pageCount"] + 1))
    return [base64.b64decode(p["imageBase64"], validate=True) for p in data["pages"]]


def test_the_endpoint_returns_every_page_as_json_and_stores_nothing(monkeypatch):
    def no_write(*args, **kwargs):
        pytest.fail("渲染结果图不能写任何状态")
    monkeypatch.setattr(main, "flush_state", no_write)
    monkeypatch.setattr(main, "flush_mutation_records", no_write)
    before = repo.state.copy()
    one = client.post(URL, headers=INSPECTION, json=short())
    assert one.status_code == 200 and one.json()["code"] == 0, one.text
    assert one.headers["cache-control"] == "no-store" and len(pages_of(one)) == 1
    many = pages_of(client.post(URL, headers=INSPECTION, json=long(30)))
    assert len(many) > 2 and all(p.startswith(b"\x89PNG") for p in many) and {decode(p).size for p in many} == {PAGE_PX}
    assert repo.state.keys() == before.keys()


def test_the_endpoint_does_not_take_the_tenant_write_lock_or_write_an_audit_record(monkeypatch):
    """渲染要几秒：抢了租户写锁会堵住同租户所有写操作；也不该留审计记录（不存储输入）。"""
    assert main.is_ephemeral_inspection_request(type("R", (), {"method": "POST", "url": type("U", (), {"path": "/api/inspection-services/audit-result-image"})()})())
    taken = []
    monkeypatch.setattr(main, "tenant_mutation_lock", lambda *a, **k: taken.append(1) or pytest.fail("不该拿租户写锁"))
    audits_before = len(repo.state.get("audit_logs", []))
    assert client.post(URL, headers=INSPECTION, json=short()).status_code == 200
    assert not taken and len(repo.state.get("audit_logs", [])) == audits_before


def test_the_endpoint_needs_login_and_a_role_that_may_use_it(monkeypatch):
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "true")
    anonymous = client.post(URL, json=short())  # 不是公开接口。这个服务器的业务错误都回 HTTP 200，原因在 JSON 里
    assert anonymous.json()["data"]["reason"] == "AUTH_REQUIRED" and "pages" not in anonymous.text
    allowed = client.post(URL, json=short(), headers={"Authorization": "Bearer dev-token-inspection"})
    assert allowed.json()["code"] == 0 and pages_of(allowed)[0].startswith(b"\x89PNG")
    denied = client.post(URL, json=short(), headers={"Authorization": "Bearer dev-token-contractor"})
    assert denied.json()["data"]["reason"] == "FORBIDDEN" and "pages" not in denied.text


def test_the_endpoint_says_what_is_wrong_with_the_request():
    invalid_json = client.post(URL, headers=INSPECTION, content=b"{not json")
    assert invalid_json.status_code == 400 and invalid_json.json()["data"]["reason"] == "VALIDATION_ERROR"
    bad = client.post(URL, headers=INSPECTION, json=summary(outcome="maybe"))
    assert bad.status_code == 400 and "outcome" in bad.json()["message"]
    huge = client.post(URL, headers=INSPECTION, json=summary(summary="x" * (ari.MAX_BODY_BYTES + 10)))
    assert huge.status_code == 413 and huge.json()["data"]["reason"] == "FILE_TOO_LARGE"


def test_content_that_is_too_long_is_the_callers_to_fix_not_a_server_error(monkeypatch):
    def too_long(*args, **kwargs):
        raise ari.AuditImageError("内容过长：超过 16 页。", client=True)

    monkeypatch.setattr(routes, "render_in_subprocess", too_long)
    response = client.post(URL, headers=INSPECTION, json=long(30))
    assert response.status_code == 400 and "内容过长" in response.json()["message"]


def test_the_endpoint_renders_at_most_two_at_a_time_and_says_when_to_retry():
    held = [routes.RENDER_SLOTS.acquire(blocking=False) for _ in range(2)]
    try:
        busy = client.post(URL, headers=INSPECTION, json=short())
    finally:
        for _ in held:
            routes.RENDER_SLOTS.release()
    assert busy.status_code == 429 and busy.headers["retry-after"] == routes.RETRY_AFTER_SECONDS
    assert client.post(URL, headers=INSPECTION, json=short()).status_code == 200  # 释放后恢复


def test_a_render_failure_is_reported_without_leaking_details_and_frees_the_slot(monkeypatch):
    def broken(*args, **kwargs):
        raise ari.AuditImageError("内部细节 /app/secret/path", retryable=True)

    monkeypatch.setattr(routes, "render_in_subprocess", broken)
    failed = client.post(URL, headers=INSPECTION, json=short())
    assert failed.status_code == 503 and "内部细节" not in failed.text and "/app/" not in failed.text
    monkeypatch.undo()
    assert client.post(URL, headers=INSPECTION, json=short()).status_code == 200  # 槽位已释放
