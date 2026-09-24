"""Get Jev answers for the inspector packet, then score them against the inspectors' labels.

`jev` asks Jev about every item in the packet key (real OCR, owner-approved; the key
is read from the terminal) and writes the answers to a private file. `score` checks
both inspector sheets, reports their agreement (Cohen's kappa) and writes the rows
they disagree on for adjudication; once every scored row has one agreed or
adjudicated verdict, it reports how well the system's "suspect" flag finds wrong
extractions: catches, false alarms and precision, with Wilson intervals, for Jev
alone and for Jev plus the local plausibility check. "看不清" rows are left out.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any

from libs.review_orchestrator.jev_fact_check import check_facts
from scripts.evaluate_jev_fact_check_real import load_snapshot
from scripts.prepare_jev_fact_labels import VERDICTS

ID_COLUMN = "条目编号"
VERDICT_COLUMN = "判定（正确/错误/原文没有/看不清）"
VALUE_COLUMN = "正确值（判定为错误时填写）"
WRONG = frozenset({"错误", "原文没有"})


def read_sheet(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row[ID_COLUMN]: row for row in csv.DictReader(handle)}


def validate(sheet: dict[str, dict[str, str]], ids: set[str], name: str) -> list[str]:
    problems = [f"{name}:missing_rows:{len(ids - set(sheet))}"] if ids - set(sheet) else []
    problems += [f"{name}:unknown_rows:{len(set(sheet) - ids)}"] if set(sheet) - ids else []
    for item_id, row in sheet.items():
        verdict = row.get(VERDICT_COLUMN, "").strip()
        if verdict and verdict not in VERDICTS:
            problems.append(f"{name}:{item_id}:invalid_verdict:{verdict}")
    return problems


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    observed = sum(a == b for a, b in pairs) / len(pairs)
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[key] * right[key] for key in set(left) | set(right)) / (len(pairs) ** 2)
    return 1.0 if expected == 1 else round((observed - expected) / (1 - expected), 3)


def wilson(hits: int, total: int) -> str:
    if not total:
        return "n/a"
    p, z = hits / total, 1.96
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return f"{hits}/{total} ({max(centre - half, 0):.0%}–{min(centre + half, 1):.0%})"


def final_verdicts(a: dict[str, dict[str, str]], b: dict[str, dict[str, str]],
                   adjudicated: dict[str, dict[str, str]] | None) -> tuple[dict[str, str], list[str]]:
    """Agreed verdicts, overridden by adjudication; returns (verdicts, ids still open)."""
    verdicts, open_ids = {}, []
    for item_id in sorted(set(a) & set(b)):
        left = a[item_id].get(VERDICT_COLUMN, "").strip()
        right = b[item_id].get(VERDICT_COLUMN, "").strip()
        ruling = ((adjudicated or {}).get(item_id) or {}).get(VERDICT_COLUMN, "").strip()
        if ruling:
            verdicts[item_id] = ruling
        elif left and left == right:
            verdicts[item_id] = left
        else:
            open_ids.append(item_id)
    return verdicts, open_ids


def metrics(verdicts: dict[str, str], items: dict[str, dict[str, Any]], answers: dict[str, dict[str, Any]]) -> dict:
    scored = {item_id: verdict for item_id, verdict in verdicts.items() if verdict != "看不清" and item_id in answers}
    wrong = [item_id for item_id, verdict in scored.items() if verdict in WRONG]
    right = [item_id for item_id, verdict in scored.items() if verdict == "正确"]

    def flagged(item_id: str, *, local: bool) -> bool:
        return bool(answers[item_id].get("suspect")) or (local and items[item_id].get("plausible") is False)

    report = {"scoredItems": len(scored), "wrongExtractions": len(wrong), "correctExtractions": len(right)}
    for name, local in (("jevOnly", False), ("jevPlusLocal", True)):
        caught = sum(flagged(item_id, local=local) for item_id in wrong)
        alarms = sum(flagged(item_id, local=local) for item_id in right)
        report[name] = {"wrongCaught": wilson(caught, len(wrong)), "correctFlagged": wilson(alarms, len(right)),
                        "precision": wilson(caught, caught + alarms)}
    report["missedWrongIds"] = sorted(item_id for item_id in wrong if not flagged(item_id, local=True))
    return report


def collect_jev(key: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_group: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in key["items"]:
        by_group.setdefault((item["projectId"], "|".join(item["documentVersionIds"])), []).append(item)
    answers: dict[str, dict[str, Any]] = {}
    for index, ((project, _versions), group) in enumerate(sorted(by_group.items()), 1):
        print(f"\rrequest {index}/{len(by_group)}", end="", flush=True)
        os.environ["AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS"] = project
        run = {"projectId": project, "tenantId": group[0]["tenantId"], "reviewMode": "formal",
               "inputDocumentVersionIds": group[0]["documentVersionIds"]}
        outcome = check_facts(snapshot, run, [{**item, "atomicCheckId": item["id"]} for item in group])
        # 本地直接标记的条目排在前面，顺序与输入不同：按条目编号（放在 atomicCheckId 里）对回去。
        for fact in outcome.get("facts") or []:
            answers[str(fact.get("atomicCheckId"))] = {name: fact.get(name) for name in (
                "status", "choice", "confidence", "suspect", "lowConfidence", "pageWindow", "excerptOnly")}
    print()
    return answers


def _private_json(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    jev = commands.add_parser("jev")
    jev.add_argument("--key", required=True, type=Path)
    jev.add_argument("--output", required=True, type=Path)
    score = commands.add_parser("score")
    score.add_argument("--key", required=True, type=Path)
    score.add_argument("--a", required=True, type=Path)
    score.add_argument("--b", required=True, type=Path)
    score.add_argument("--adjudicated", type=Path)
    score.add_argument("--jev", type=Path)
    score.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    key = json.loads(args.key.read_text(encoding="utf-8"))
    if args.command == "jev":
        os.environ["AICHECK_CERT_PLATFORM_VERIFY"] = "off"
        snapshot = load_snapshot(Path(key["snapshot"]))
        secret = getpass.getpass("Jev test API key: ").strip()
        if not secret:
            parser.error("jev_test_key_required")
        os.environ.update({"AICHECK_JEV_API_KEY": secret, "AICHECK_JEV_ENABLED": "true",
                           "AICHECK_JEV_DATA_EGRESS_APPROVED": "true", "AICHECK_JEV_FACT_CHECK_ENABLED": "true"})
        try:
            answers = collect_jev(key, snapshot)
        finally:
            os.environ.pop("AICHECK_JEV_API_KEY", None)
        _private_json(args.output, {"packet": str(args.key), "answers": answers})
        print(json.dumps({"answered": sum(1 for row in answers.values() if row.get("choice")),
                          "items": len(key["items"])}, ensure_ascii=False))
        return 0
    ids = {item["id"] for item in key["items"]}
    a, b = read_sheet(args.a), read_sheet(args.b)
    adjudicated = read_sheet(args.adjudicated) if args.adjudicated else None
    problems = validate(a, ids, "A") + validate(b, ids, "B")
    pairs = [(a[i][VERDICT_COLUMN].strip(), b[i][VERDICT_COLUMN].strip()) for i in sorted(ids & set(a) & set(b))
             if a[i][VERDICT_COLUMN].strip() and b[i][VERDICT_COLUMN].strip()]
    verdicts, open_ids = final_verdicts(a, b, adjudicated)
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if open_ids:
        descriptor = os.open(args.output_dir / "adjudication.csv", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([ID_COLUMN, "A 判定", "A 正确值", "B 判定", "B 正确值", VERDICT_COLUMN, "说明"])
            for item_id in open_ids:
                writer.writerow([item_id, a[item_id][VERDICT_COLUMN], a[item_id][VALUE_COLUMN],
                                 b[item_id][VERDICT_COLUMN], b[item_id][VALUE_COLUMN], "", ""])
    report: dict[str, Any] = {"problems": problems, "pairedLabels": len(pairs),
                              "agreement": wilson(sum(x == y for x, y in pairs), len(pairs)),
                              "cohenKappa": cohen_kappa(pairs), "openForAdjudication": len(open_ids),
                              "finalVerdicts": dict(Counter(verdicts.values()))}
    if args.jev and not open_ids and not problems:
        answers = json.loads(args.jev.read_text(encoding="utf-8"))["answers"]
        report["metrics"] = metrics(verdicts, {item["id"]: item for item in key["items"]}, answers)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if not problems else 2


if __name__ == "__main__":
    raise SystemExit(main())
