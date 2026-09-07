"""同步 TSG 安全技术规范目录到 standard_version_timeline.yaml（P11 N-03；默认 dry-run）。

三段抓取（《研究-TSG规范在线核验源》）：
1. 目录：特种设备局"安全技术规范"分页接口（GET，paramJson={"pageNo":N,"pageSize":10}），
   解析标题、TSG 编号、发布日期、详情页；解析不出编号的（修改单公告、试行文件）单独列出，不进时间线。
2. 公告/详情页：抓"自 YYYY 年 M 月 D 日起施行"与"对《X》（TSG …）进行了修订/整合修订"，得实施日期与被修订编号。
3. 附则（PDF OCR）不在本脚本里自动做——扫描件 38 MB，OCR 只做附则页；抽到的废止列表以 extractionMethod=ocr_unverified
   写入，人工核对后改 verifiedBy。

只新增/补齐目录与公告字段，不覆盖已有 verifiedBy 的条目里的人工字段。
用法：python scripts/sync_tsg_catalog.py            # dry-run，打印将要新增/更新的条目
      python scripts/sync_tsg_catalog.py --apply    # 写 yaml
      python scripts/sync_tsg_catalog.py --from-json catalog.json   # 用已抓好的目录 JSON（离线）
"""

from __future__ import annotations

import argparse
import html as htmlmod
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

BACKEND_ROOT = Path(__file__).resolve().parents[1] if "__file__" in globals() else Path("/app")
sys.path.insert(0, str(BACKEND_ROOT))

from libs.standard_timeline import TIMELINE_PATH, normalize_code

CATALOG_ORIGIN = "https://www.samr.gov.cn"
CATALOG_ENDPOINT = "/api-gateway/jpaas-publish-server/front/page/build/unit"
# 固定参数必须和 paramJson 一起以 params 传：httpx 的 params 会整体替换 URL 自带的查询串（2026-09-06 实测返回 success=false、data={}）
CATALOG_PARAMS = {
    "parseType": "bulidstatic",
    "webId": "29e9522dc89d4e088a953d8cede72f4c",
    "tplSetId": "5c30fb89ae5e48b9aefe3cdf49853830",
    "pageType": "column",
    "tagId": "ajax分页",
    "editType": "null",
    "pageId": "6b042a0744f4442c928a9a6aff47129f",
}
_ITEM_RE = re.compile(r'<a\s+href="([^"]+)"\s+title="([^"]*)"[^>]*>.*?</a>\s*<div class="contentRight01time">(\d{4}-\d{2}-\d{2})</div>', re.DOTALL)
_COUNT_RE = re.compile(r'count="(\d+)"')
_TSG_IN_TITLE_RE = re.compile(r"TSG\s*([A-Z]{0,2}\s?\d{2,5})\s*[-—–－]\s*(\d{4})", re.IGNORECASE)
_EFFECTIVE_RE = re.compile(r"自\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*起\s*(?:施行|实施|执行)")
_REVISED_RE = re.compile(r"[（(]\s*(TSG\s*[A-Z]{0,2}\s?\d{2,5}\s*[-—–－]\s*\d{4})\s*[）)]")


def parse_catalog_html(page_html: str) -> tuple[list[dict[str, Any]], int | None]:
    """目录页 HTML → [{title, code, date, url}], 总条数。"""
    rows: list[dict[str, Any]] = []
    for href, title, day in _ITEM_RE.findall(page_html or ""):
        clean_title = htmlmod.unescape(title).strip()
        match = _TSG_IN_TITLE_RE.search(clean_title)
        rows.append(
            {
                "title": clean_title,
                "code": normalize_code(match.group(0)) if match else None,
                "date": day,
                "url": href if href.startswith("http") else CATALOG_ORIGIN + href,
            }
        )
    count = _COUNT_RE.search(page_html or "")
    return rows, int(count.group(1)) if count else None


def parse_announcement_text(text: str) -> dict[str, Any]:
    """公告/详情正文 → {effectiveFrom, supersedes[]}。措辞固定，不做语义推断。"""
    plain = re.sub(r"<[^>]+>", " ", text or "")
    plain = htmlmod.unescape(plain)
    effective = _EFFECTIVE_RE.search(plain)
    # 公告措辞："对《A》（TSG …）《B》（TSG …）进行(整合)修订，形成《C》（TSG …）"：被修订编号都在第一个"修订"之前，
    # 新编号在其后；只取"修订"之前的括号编号，不做语义推断。
    revised_prefix = plain.split("修订", 1)[0] if "修订" in plain else ""
    supersedes = list(dict.fromkeys(normalize_code(match) for match in _REVISED_RE.findall(revised_prefix)))
    return {
        "effectiveFrom": f"{effective.group(1)}-{int(effective.group(2)):02d}-{int(effective.group(3)):02d}" if effective else None,
        "supersedes": supersedes,
    }


def fetch_catalog(page_size: int = 10, *, timeout: float = 20.0) -> list[dict[str, Any]]:
    import httpx

    rows: list[dict[str, Any]] = []
    total: int | None = None
    page_no = 1
    with httpx.Client(timeout=timeout, headers={"User-Agent": "Mozilla/5.0 AIcheck-tsg-sync"}) as client:
        while True:
            params = {**CATALOG_PARAMS, "paramJson": json.dumps({"pageNo": page_no, "pageSize": page_size}, separators=(",", ":"))}
            response = client.get(CATALOG_ORIGIN + CATALOG_ENDPOINT, params=params)
            response.raise_for_status()
            payload = response.json()
            page_rows, count = parse_catalog_html(((payload.get("data") or {}).get("html")) if isinstance(payload.get("data"), dict) else "")
            rows.extend(page_rows)
            total = total or count
            if not page_rows or (total is not None and len(rows) >= total) or page_no > 50:
                break
            page_no += 1
    return rows


def fetch_announcement(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    import httpx

    with httpx.Client(timeout=timeout, headers={"User-Agent": "Mozilla/5.0 AIcheck-tsg-sync"}) as client:
        response = client.get(url)
        response.raise_for_status()
        return parse_announcement_text(response.text)


def merge_catalog(timeline: dict[str, Any], rows: list[dict[str, Any]], announcements: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """把目录行合并进时间线：新编号新增（extractionMethod=catalog），已有条目只补空字段，不动人工字段。"""
    entries: list[dict[str, Any]] = [dict(item) for item in timeline.get("entries") or [] if isinstance(item, dict)]
    by_code = {normalize_code(str(item.get("code"))): item for item in entries if item.get("code")}
    changes: list[dict[str, Any]] = []
    for row in rows:
        code = row.get("code")
        if not code:
            continue
        info = (announcements or {}).get(code) or {}
        entry = by_code.get(code)
        if entry is None:
            entry = {
                "code": code,
                "name": re.sub(r"[（(]\s*TSG.*$", "", row["title"]).strip(),
                "catalogDate": row.get("date"),
                "effectiveFrom": info.get("effectiveFrom"),
                "supersedes": info.get("supersedes") or [],
                "sourceUrls": {"catalog": row.get("url")},
                "extractionMethod": "catalog+announcement" if info else "catalog",
                "verifiedBy": None,
            }
            entries.append(entry)
            by_code[code] = entry
            changes.append({"action": "add", "code": code, "effectiveFrom": entry["effectiveFrom"], "supersedes": entry["supersedes"]})
            for old in entry["supersedes"]:
                old_entry = by_code.get(old)
                if old_entry is None:
                    old_entry = {"code": old, "replacedBy": code, "withdrawnOn": entry["effectiveFrom"], "extractionMethod": "announcement", "verifiedBy": None}
                    entries.append(old_entry)
                    by_code[old] = old_entry
                    changes.append({"action": "add_superseded", "code": old, "replacedBy": code, "withdrawnOn": entry["effectiveFrom"]})
            continue
        updated = []
        for key, value in (("catalogDate", row.get("date")), ("effectiveFrom", info.get("effectiveFrom"))):
            if value and not entry.get(key):
                entry[key] = value
                updated.append(key)
        urls = dict(entry.get("sourceUrls") or {})
        if row.get("url") and not urls.get("catalog"):
            urls["catalog"] = row["url"]
            entry["sourceUrls"] = urls
            updated.append("sourceUrls.catalog")
        if updated:
            changes.append({"action": "update", "code": code, "fields": updated})
    return {**timeline, "entries": entries, "updatedAt": datetime.now(UTC).date().isoformat()}, changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--from-json", help="离线目录 JSON（[{title, tsg|code, date, url}]），不联网")
    parser.add_argument("--announcements", action="store_true", help="对新增条目抓详情页解析实施日期与被修订编号")
    parser.add_argument("--timeline", default=str(TIMELINE_PATH))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.from_json:
        raw = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        rows = [
            {"title": item.get("title"), "code": normalize_code(f"TSG {item['tsg']}") if item.get("tsg") else item.get("code"), "date": item.get("date"), "url": item.get("url")}
            for item in raw
            if isinstance(item, dict)
        ]
    else:
        rows = fetch_catalog()
    timeline_path = Path(args.timeline)
    timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8")) if timeline_path.exists() else {"schemaVersion": "standard-version-timeline-v1", "entries": []}
    known = {normalize_code(str(item.get("code"))) for item in timeline.get("entries") or [] if isinstance(item, dict) and item.get("code")}
    announcements: dict[str, dict[str, Any]] = {}
    if args.announcements:
        for row in rows:
            if row.get("code") and row["code"] not in known and row.get("url"):
                try:
                    announcements[row["code"]] = fetch_announcement(row["url"])
                except Exception as exc:  # noqa: BLE001 —— 单页失败只记录，继续
                    announcements[row["code"]] = {"error": repr(exc)[:120]}
    merged, changes = merge_catalog(timeline, rows, announcements)
    unparsed = [row["title"] for row in rows if not row.get("code")]
    print(json.dumps({"apply": args.apply, "catalogRows": len(rows), "unparsedTitles": unparsed, "changes": changes}, ensure_ascii=False, indent=2))
    if args.apply:
        timeline_path.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"written {timeline_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
