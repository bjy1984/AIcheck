"""Run a tiny, explicitly synthetic Jev integration probe.

No project fixture or OCR export is loaded. The optional API key is read from
the terminal and only kept in this process. This measures the live integration,
not business accuracy or the pending 33 inspector-labelled questions.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import time
from typing import Any

from libs.review_orchestrator.jev_claims import verify_finding_claims
from libs.review_orchestrator.jev_opinion import second_opinions
from libs.review_orchestrator.jev_tables import business_rows, classify_review_tables


def synthetic_case() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Fictional WPS and mechanical-test text with no person or real project data."""
    state = {
        "documents": [{"id": "SYN-DOC", "projectId": "SYNTHETIC-JEV-EVAL", "fileName": "synthetic-wps.txt"}],
        "document_versions": [{"id": "SYN-V1", "documentId": "SYN-DOC"}],
        "ocr_parse_results": [{
            "documentVersionId": "SYN-V1",
            "fragments": [{"pageNo": 1, "text": (
                "以下内容完全虚构，仅供模型测试。表格1为力学性能试验结果：抗拉强度520 MPa，弯曲试验合格。"
                "表格2为焊接工艺参数：焊接电流90A，电压20V。没有记录900A。"
            )}],
            "tables": [
                {"pageNo": 1, "normalizedRows": [
                    {"项目": "抗拉强度", "数值": "520 MPa"},
                    {"项目": "弯曲试验", "数值": "合格"},
                ]},
                {"pageNo": 1, "normalizedRows": [
                    {"栏目": "焊接参数", "电流": "", "电压": ""},
                    {"栏目": "正式记录", "电流": "90A", "电压": "20V"},
                    {"栏目": "待填写", "电流": "", "电压": ""},
                ]},
            ],
        }],
    }
    review_run = {"projectId": "SYNTHETIC-JEV-EVAL", "nodeId": 25,
                  "inputDocumentVersionIds": ["SYN-V1"]}
    rule_results = [{"atomicCheckResults": [
        {"atomicCheckId": "SYN-AC-1", "result": "passed"},
        {"atomicCheckId": "SYN-AC-2", "result": "passed"},
        {"atomicCheckId": "SYN-AC-3", "result": "evidence_insufficient"},
    ]}]
    pack = {"atomicChecks": [
        {"id": "SYN-AC-1", "nodeId": 25, "instruction": "这份示例工艺参数表是否记录了90A焊接电流"},
        {"id": "SYN-AC-2", "nodeId": 25, "instruction": "这份示例工艺参数表是否记录了900A焊接电流"},
        {"id": "SYN-AC-3", "nodeId": 25, "instruction": "这份示例文件是否证明焊工甲有有效资格证书"},
    ]}
    return state, review_run, rule_results, pack


def run_probe() -> dict[str, Any]:
    state, review_run, rule_results, pack = synthetic_case()
    os.environ["AICHECK_JEV_ENABLED"] = "true"
    os.environ["AICHECK_JEV_DATA_EGRESS_APPROVED"] = "true"
    for stage in ("TABLE_CLASSIFICATION", "CLAIM_SHADOW", "SECOND_OPINION"):
        os.environ[f"AICHECK_JEV_{stage}_ENABLED"] = "true"
    # This probe must never turn on release gates or change visible findings.
    for gate in ("AICHECK_JEV_CALIBRATION_APPROVED", "AICHECK_JEV_CLAIM_GATE_ENABLED",
                 "AICHECK_JEV_SECOND_OPINION_UI_ENABLED"):
        os.environ.pop(gate, None)

    started = time.monotonic()
    tables = classify_review_tables(state, review_run)
    table_seconds = time.monotonic() - started
    parsed = state["ocr_parse_results"][0]
    filtered_rows = business_rows(parsed, tables, skip_mechanical=True)

    drafts = [
        {"id": "SYN-F1", "title": "90A 记录", "description": "焊接电流为90A。",
         "claims": ["焊接电流为90A"], "confidence": 0.9},
        {"id": "SYN-F2", "title": "900A 记录", "description": "焊接电流为900A。",
         "claims": ["焊接电流为900A"], "confidence": 0.9},
    ]
    started = time.monotonic()
    claims = verify_finding_claims(state, review_run, rule_results, drafts)
    claim_seconds = time.monotonic() - started

    started = time.monotonic()
    opinion = second_opinions(state, review_run, rule_results, pack)
    opinion_seconds = time.monotonic() - started

    table_types = [row["tableType"] for row in tables.get("tables", {}).get("SYN-V1", [])]
    row_roles = [[role for role in row["rowRoles"]]
                 for row in tables.get("tables", {}).get("SYN-V1", [])]
    claim_results = [row["claims"][0] for row in claims.get("findings", [])]
    atomic = opinion.get("atomic") or []
    opinions = {row["atomicCheckId"]: row for row in atomic}
    checks = {
        "mechanical_table_identified": bool(table_types and table_types[0]["choice"] == "mech_test"),
        "wps_table_identified": bool(len(table_types) > 1 and table_types[1]["choice"] == "wps_parameters"),
        "subtitle_identified": bool(len(row_roles) > 1 and len(row_roles[1]) > 0
                                    and row_roles[1][0]["choice"] == "subtitle"),
        "template_identified": bool(len(row_roles) > 1 and len(row_roles[1]) > 2
                                    and row_roles[1][2]["choice"] == "template"),
        "only_wps_data_row_used": filtered_rows == [parsed["tables"][1]["normalizedRows"][1]],
        "supported_90a_claim": bool(claim_results and claim_results[0]["choice"] == "supported"),
        "rejected_900a_claim": bool(len(claim_results) > 1 and claim_results[1]["choice"] in
                                   {"contradicted", "not_in_materials"}),
        "literal_second_opinion": opinions.get("SYN-AC-1", {}).get("choice") == "passed",
        "disagreement_detected": (opinions.get("SYN-AC-2", {}).get("choice") == "failed"
                                  and opinions["SYN-AC-2"]["agreesWithRuleEngine"] is False),
        "missing_evidence_not_passed": opinions.get("SYN-AC-3", {}).get("choice") in
                                       {"evidence_insufficient", "human_review_required"},
        "deterministic_verdict_unchanged": [row["result"] for row in rule_results[0]["atomicCheckResults"]]
                                           == ["passed", "passed", "evidence_insufficient"],
        "finding_text_unchanged_in_shadow": drafts[1]["description"] == "焊接电流为900A。",
    }
    return {
        "fixture": "synthetic_only", "model": "jev-1.13.0",
        "status": {"tables": tables["status"], "claims": claims["status"], "secondOpinion": opinion["status"]},
        "checks": checks,
        "choices": {
            "tables": [{"choice": row["choice"], "confidence": row["confidence"]} for row in table_types],
            "rowRoles": [[{"choice": role["choice"], "confidence": role["confidence"]} for role in group]
                         for group in row_roles],
            "claims": claim_results,
            "secondOpinion": [{"atomicCheckId": row["atomicCheckId"], "choice": row["choice"],
                               "confidence": row["confidence"], "agreesWithRuleEngine":
                               row["agreesWithRuleEngine"]} for row in atomic],
        },
        "elapsedSeconds": {"tables": round(table_seconds, 3), "claims": round(claim_seconds, 3),
                           "secondOpinion": round(opinion_seconds, 3)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-key", action="store_true", help="Read a test API key without echoing or saving it")
    parser.add_argument("--repeat", type=int, default=1, choices=range(1, 6), metavar="1..5")
    args = parser.parse_args()
    if args.prompt_key:
        os.environ["AICHECK_JEV_API_KEY"] = getpass.getpass("Jev test API key: ").strip()
    if not os.environ.get("AICHECK_JEV_API_KEY"):
        parser.error("AICHECK_JEV_API_KEY is required")
    try:
        rounds = [run_probe() for _ in range(args.repeat)]
    finally:
        os.environ.pop("AICHECK_JEV_API_KEY", None)
    report = {"fixture": "synthetic_only", "rounds": rounds,
              "allChecksPassed": all(all(row["checks"].values()) for row in rounds)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["allChecksPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
