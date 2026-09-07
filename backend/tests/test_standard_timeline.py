"""P11 N-03：TSG 版本时间线——本地优先判 现行 / 过渡期作废 / 已废止 / 未收录；目录与公告解析。"""

from __future__ import annotations

from libs.standard_timeline import normalize_code, standard_reference_fact, timeline_status
from scripts.sync_tsg_catalog import merge_catalog, parse_announcement_text, parse_catalog_html

PAGE_HTML = """
<ul>
  <li class="content-3-left-text imgContent01new">
    <a href="/tzsbj/zcfg/aqjsgf/art/2026/art_d047.html" title="特种设备焊接操作人员考核细则（TSG Z6002—2026）" target="_blank">x</a>
    <div class="contentRight01time">2026-03-19</div>
  </li>
  <li class="content-3-left-text imgContent01new">
    <a href="/tzsbj/zcfg/aqjsgf/art/2026/art_3d46.html" title="工业管道安全技术规程（TSG 31—2025）" target="_blank">x</a>
    <div class="contentRight01time">2025-10-30</div>
  </li>
  <li class="content-3-left-text imgContent01new">
    <a href="/tzsbj/zcfg/aqjsgf/art/2025/art_abcd.html" title="关于发布《XX》第1号修改单的公告" target="_blank">x</a>
    <div class="contentRight01time">2025-05-30</div>
  </li>
</ul>
<div class="page" count="111"></div>
"""


def test_codes_normalize_across_dash_and_spacing_variants() -> None:
    assert normalize_code("TSG Z6002—2026") == "TSG Z6002-2026"
    assert normalize_code("tsg z6002－2026") == "TSG Z6002-2026"
    assert normalize_code("TSG 31—2025") == "TSG 31-2025"
    assert normalize_code("GB/T 20801.1—2025") == "GB/T 20801.1-2025"


def test_timeline_status_follows_effective_and_withdrawn_dates() -> None:
    assert timeline_status("TSG 31-2025", "2026-09-06")["status"] == "current"
    assert timeline_status("TSG 31-2025", "2025-12-01")["status"] == "not_yet_effective"
    old = timeline_status("TSG D0001—2009", "2026-09-06")
    assert old["status"] == "withdrawn" and old["replacedBy"] == "TSG 31-2025" and old["verified"] is True
    assert timeline_status("TSG D0001-2009", "2025-12-31")["status"] == "current", "废止日前仍现行"
    assert timeline_status("TSG Z6002-2010", "2026-07-31")["status"] == "current"
    assert timeline_status("TSG Z6002-2010", "2026-08-01")["status"] == "withdrawn"
    unknown = timeline_status("TSG D7006-2020", "2026-09-06")
    assert unknown["status"] == "unknown" and unknown["verified"] is False


def test_reference_fact_only_marks_verified_withdrawals_as_withdrawn() -> None:
    fact = standard_reference_fact("TSG D0001-2009", "2026-09-06")
    assert fact["status"] == "withdrawn" and fact["withdrawnOn"] == "2026-01-01"
    current = standard_reference_fact("TSG 31-2025", "2026-09-06")
    assert current["status"] == "active" and current["withdrawnOn"] is None
    unknown = standard_reference_fact("TSG D7006-2020", "2026-09-06")
    assert unknown["status"] == "unknown" and unknown["requiresOnlineLookup"] is True


def test_catalog_and_announcement_parsers_extract_codes_dates_and_revision_targets() -> None:
    rows, total = parse_catalog_html(PAGE_HTML)
    assert total == 111
    assert [row["code"] for row in rows] == ["TSG Z6002-2026", "TSG 31-2025", None]
    assert rows[0]["date"] == "2026-03-19" and rows[0]["url"].startswith("https://www.samr.gov.cn/")
    announcement = parse_announcement_text(
        "对《压力管道安全技术监察规程—工业管道》（TSG D0001—2009）《压力管道定期检验规则—工业管道》（TSG D7005—2018）进行整合修订，"
        "形成《工业管道安全技术规程》（TSG 31—2025），现予批准发布，自2026年1月1日起施行。"
    )
    assert announcement == {"effectiveFrom": "2026-01-01", "supersedes": ["TSG D0001-2009", "TSG D7005-2018"]}


def test_merge_adds_new_codes_and_never_overwrites_verified_entries() -> None:
    timeline = {"entries": [{"code": "TSG 31-2025", "effectiveFrom": "2026-01-01", "verifiedBy": "人工", "sourceUrls": {}}]}
    rows, _ = parse_catalog_html(PAGE_HTML)
    merged, changes = merge_catalog(timeline, rows, {"TSG Z6002-2026": {"effectiveFrom": "2026-08-01", "supersedes": ["TSG Z6002-2010"]}})
    by_code = {item["code"]: item for item in merged["entries"]}
    assert by_code["TSG 31-2025"]["verifiedBy"] == "人工" and by_code["TSG 31-2025"]["effectiveFrom"] == "2026-01-01"
    assert by_code["TSG 31-2025"]["sourceUrls"]["catalog"].endswith("art_3d46.html"), "只补空字段"
    assert by_code["TSG Z6002-2026"]["extractionMethod"] == "catalog+announcement" and by_code["TSG Z6002-2026"]["verifiedBy"] is None
    assert by_code["TSG Z6002-2010"]["replacedBy"] == "TSG Z6002-2026" and by_code["TSG Z6002-2010"]["withdrawnOn"] == "2026-08-01"
    assert [change["action"] for change in changes] == ["add", "add_superseded", "update"]
