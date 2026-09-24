"""Known-answer probe: can Jev confirm or reject an extracted certificate date?

Every licence text here is fictional, so nothing from a project leaves this
machine. Each wording is asked about three claimed validity end dates: the
correct one, the start date that the old extractor produced for ranges, and a
date one year off. The truth is known by construction, so the report gives how
often Jev rejects a wrong value, how often it rejects a right one, how often it
abstains, and whether two identical runs agree. The key is read from the
terminal and kept only in this process.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from libs.review_orchestrator.jev_client import ask_jev

SCHEMA_VERSION = "jev-extraction-check-v1"
HEAD = ["中华人民共和国特种设备生产许可证", "许可证编号：TS3841999-2028", "单位名称：示例管道安装有限公司",
        "许可项目：压力管道安装", "许可子项目：工业管道安装（GC1）"]
TAIL = ["发证机关：示例省市场监督管理局", "以上内容完全虚构，仅供模型测试。"]
BUNDLE_TAIL = ["另附：示例认证中心产品认证证书", "证书有效日期：2021年06月30日至2024年06月29日"]
CHOICES = {
    "yes": "原文明确写明这张许可证的有效期截止日就是题目给出的日期",
    "no": "原文写明的截止日与题目给出的日期不同，或题目给出的其实是起始日、发证日期或其他证书的日期",
    "cannot_determine": "原文没有写明这张许可证的截止日，或文字无法辨认，无法判断",
}
# (case id, validity lines, true validUntil, start date the old extractor returned or None)
CASES: list[tuple[str, list[str], str, str | None]] = [
    ("until_only", ["有效期至：2028年9月6日"], "2028-09-06", None),
    ("range_cn_one_line", ["有效期：2024年9月7日至2028年9月6日"], "2028-09-06", "2024-09-07"),
    ("range_cn_padded", ["有效期限：2024年09月07日至2028年09月06日"], "2028-09-06", "2024-09-07"),
    ("range_dot", ["有效期：2024.09.07-2028.09.06"], "2028-09-06", None),
    ("range_zi", ["有效期自2024年9月7日至2028年9月6日"], "2028-09-06", "2024-09-07"),
    ("range_emdash", ["有效期：2024年9月7日—2028年9月6日"], "2028-09-06", "2024-09-07"),
    ("label_then_range_next_line", ["有效期", "2024年9月7日至2028年9月6日"], "2028-09-06", "2024-09-07"),
    ("issue_before_until", ["发证日期：2024年7月31日", "有效期至：2028年9月6日"], "2028-09-06", None),
    ("qi_zhi_split", ["有效期起：2024年9月7日", "有效期止：2028年9月6日"], "2028-09-06", "2024-09-07"),
    ("range_ocr_spaces", ["有效期：2024 年 9 月 7 日 至 2028 年 9 月 6 日"], "2028-09-06", "2024-09-07"),
    ("range_suffix_youxiao", ["2024年9月7日至2028年9月6日有效"], "2028-09-06", None),
    ("bundle_other_range_after", ["有效期至：2028年05月12日", "发证日期：2023年03月08日", *BUNDLE_TAIL],
     "2028-05-12", None),
    ("no_validity_stated", ["发证日期：2024年7月31日"], "", None),
]


def _cn(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.year}年{parsed.month}月{parsed.day}日"


def claims_for(case: tuple[str, list[str], str, str | None]) -> list[dict[str, Any]]:
    _case_id, _lines, truth, old_value = case
    if not truth:
        return [{"kind": "fabricated", "claimed": "2028-09-06", "expected": "cannot_determine"}]
    off = date.fromisoformat(truth)
    rows = [{"kind": "correct", "claimed": truth, "expected": "yes"},
            {"kind": "year_off", "claimed": off.replace(year=off.year - 1).isoformat(), "expected": "no"}]
    if old_value:
        rows.append({"kind": "old_extractor_start_date", "claimed": old_value, "expected": "no"})
    return rows


def build_requests() -> list[dict[str, Any]]:
    requests = []
    for case in CASES:
        case_id, lines, _truth, _old = case
        text = "\n".join(HEAD + lines + TAIL)
        claims = claims_for(case)
        questions = {
            f"c{index}": {"type": "choice", "criteria": CHOICES, "instructions": (
                f"只看这张特种设备生产许可证本身：它的有效期截止日是否为{_cn(claim['claimed'])}？"
                "起始日、发证日期和其他证书的日期都不是截止日。")}
            for index, claim in enumerate(claims)
        }
        requests.append({"caseId": case_id, "state": text, "questions": questions, "claims": claims})
    return requests


def _share(rows: list[dict[str, Any]], choice: str) -> str:
    """How many rows got this choice in the first run, as "n/total"."""
    return f"{sum(row['choices'][0] == choice for row in rows)}/{len(rows)}"


def score(runs: list[list[dict[str, Any]]]) -> dict[str, Any]:
    rows = []
    for request_rows in zip(*runs, strict=True):
        first = request_rows[0]
        for key, claim in zip(first["questions"], first["claims"], strict=True):
            answers = [run["answers"].get(key) or {} for run in request_rows]
            rows.append({"caseId": first["caseId"], **claim,
                         "choices": [answer.get("choice") for answer in answers],
                         "confidences": [answer.get("confidence") for answer in answers]})
    wrong = [row for row in rows if row["expected"] == "no"]
    right = [row for row in rows if row["expected"] == "yes"]
    unknown = [row for row in rows if row["expected"] == "cannot_determine"]
    old_errors = [row for row in wrong if row["kind"] == "old_extractor_start_date"]
    return {
        "questionCount": len(rows),
        "wrongValueRejected": _share(wrong, "no"),
        "oldExtractorErrorRejected": _share(old_errors, "no"),
        "wrongValueAccepted": _share(wrong, "yes"),
        "rightValueConfirmed": _share(right, "yes"),
        "rightValueRejected": _share(right, "no"),
        "abstained": _share(rows, "cannot_determine"),
        "unstatedHandled": _share(unknown, "cannot_determine"),
        "sameChoiceAcrossRuns": f"{sum(len(set(row['choices'])) == 1 for row in rows)}/{len(rows)}",
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--send", action="store_true", help="call Jev; without it only print the plan")
    args = parser.parse_args()
    requests = build_requests()
    planned = {"requests": len(requests) * args.repeats,
               "questions": sum(len(r["questions"]) for r in requests) * args.repeats}
    if not args.send:
        print(json.dumps({"status": "plan_only", **planned}, ensure_ascii=False))
        return 0
    key = getpass.getpass("Jev test API key: ").strip()
    if not key:
        parser.error("jev_test_key_required")
    os.environ.update({"AICHECK_JEV_API_KEY": key, "AICHECK_JEV_ENABLED": "true",
                       "AICHECK_JEV_DATA_EGRESS_APPROVED": "true"})
    runs: list[list[dict[str, Any]]] = []
    metrics: list[dict[str, Any]] = []
    try:
        for _ in range(args.repeats):
            runs.append([{**request, "answers": ask_jev(request["state"], request["questions"],
                                                        observe=metrics.append)}
                         for request in requests])
    finally:
        os.environ.pop("AICHECK_JEV_API_KEY", None)
    report = {"schemaVersion": SCHEMA_VERSION, "fictionalInputsOnly": True, **planned,
              "requestMetrics": metrics, **score(runs)}
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in report.items() if key not in {"rows", "requestMetrics"}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
