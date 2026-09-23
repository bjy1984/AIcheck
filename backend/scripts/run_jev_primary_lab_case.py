"""Read-only, real-OCR Lab node replay: template → Qwen questions → Jev.

The seven-project snapshot is local and private. Only its scoped OCR and node
template go to Qwen; Jev receives full OCR and the authored questions. The local
database supplies installed rule configuration, and nothing is flushed back to it. Use --prompt-key for one
interactive test run; the key is never persisted by this script.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import subprocess
import zlib
from pathlib import Path
from unittest.mock import patch

from libs.business_pack.loader import matching_rule_for_node
from libs.db.repository import load_state, repo
from libs.jev_evaluation_input import approved_ocr_text
from libs.material_targeting import MANUAL_REJECTED
from libs.review_orchestrator import jev_primary
from libs.review_orchestrator.execution import run_step
from libs.review_orchestrator.jev_client import jev_stage_enabled
from libs.review_rule_snapshot import freeze_effective_rule

_QWEN_SECRET_HOST = "aicheck-prod-new"
_QWEN_SECRET_PATH = "/home/dev-bjy/aicheck-secrets.env"


def _qwen_test_key_from_server() -> str:
    """Read the DashScope test key into this process without displaying or persisting it."""
    remote_code = f"""from pathlib import Path
from urllib.parse import urlsplit
rows = dict(line.strip().split('=', 1) for line in Path({_QWEN_SECRET_PATH!r}).read_text().splitlines()
            if '=' in line and not line.lstrip().startswith('#'))
base = rows.get('AICHECK_LLM_VISION_API_BASE', '').strip('\\"\\\'')
key = rows.get('AICHECK_LLM_VISION_API_KEY', '').strip('\\"\\\'')
if urlsplit(base).hostname != 'dashscope.aliyuncs.com' or not key:
    raise SystemExit(2)
print(key, end='')
"""
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
             _QWEN_SECRET_HOST, "python3 -"], input=remote_code, text=True,
            capture_output=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("qwen_server_key_unavailable") from exc
    if result.returncode or not result.stdout.strip() or "\n" in result.stdout.strip():
        raise RuntimeError("qwen_server_key_unavailable")
    return result.stdout.strip()


def _private_write(path: Path, value: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def replay(snapshot: dict, project_id: str, node_id: int, *, send: bool,
           expected_requests: int) -> dict:
    if snapshot.get("source") != "read_only_seven_project_ocr_snapshot":
        raise ValueError("approved_seven_project_snapshot_required")
    project = next((row for row in snapshot["projects"] if row.get("id") == project_id), None)
    if not project or not isinstance(project.get("businessPackSnapshot"), dict):
        raise ValueError("project_and_frozen_pack_required")
    versions = sorted({str(row.get("documentVersionId")) for row in snapshot.get("node_evidence_links") or []
                       if row.get("projectId") == project_id and int(row.get("nodeId") or 0) == node_id
                       and row.get("manualStatus") != MANUAL_REJECTED and row.get("documentVersionId")})
    if not versions:
        raise ValueError("node_has_no_selected_documents")
    run = {"id": "JEV-LAB-REPLAY", "reviewRunId": "JEV-LAB-REPLAY", "projectId": project_id,
           "tenantId": str(project.get("tenantId") or "TENANT-DEFAULT"), "nodeId": node_id,
           "businessPackId": project.get("businessPackId"), "reviewMode": "formal",
           "advisoryOnly": False, "inputDocumentVersionIds": versions,
           "inputDocumentPageRanges": {}, "documentSources": []}
    frozen_rule = matching_rule_for_node(project["businessPackSnapshot"], node_id)
    if not frozen_rule:
        raise ValueError("frozen_node_rule_required")
    run["effectiveRuleSnapshot"] = freeze_effective_rule(run, frozen_rule)
    ocr_status, ocr_text = approved_ocr_text(snapshot, run)
    if ocr_status != "ready":
        raise ValueError("full_ocr_not_ready:" + ocr_status)
    load_state()
    if any(row.get("id") == project_id for row in repo.state.get("projects") or []):
        raise ValueError("snapshot_project_already_present_in_local_state")
    # The snapshot is a separate read-only input. Add its rows only to this
    # process's in-memory state; run_step's rule record is likewise not flushed.
    repo.state.setdefault("projects", []).append(project)
    document_ids = {str(row.get("id")) for row in snapshot["documents"]
                    if row.get("projectId") == project_id}
    for collection in ("documents", "versions", "ocr_parse_results", "node_evidence_links",
                       "extracted_fields", "evidence_links", "fact_corrections"):
        rows = snapshot.get(collection) or []
        selected = [row for row in rows if isinstance(row, dict) and (
            row.get("projectId") == project_id
            or (collection == "versions" and str(row.get("documentId")) in document_ids)
            or (collection == "ocr_parse_results" and str(row.get("documentVersionId")) in versions)
        )]
        repo.state.setdefault(collection, []).extend(selected)
    context: dict = {"reviewRun": run}
    with patch.dict(os.environ, {"AICHECK_CERT_PLATFORM_VERIFY": "off"}):
        for step in ("load_context", "load_ocr_result", "run_rule_engine"):
            run_step(run, step, context)
    rules = context.get("ruleResults") or []
    if not rules or not rules[0].get("atomicCheckResults"):
        raise ValueError("no_actual_rule_execution")
    merged_ocr_status, merged_ocr_text = approved_ocr_text(repo.state, run)
    if merged_ocr_status != "ready" or merged_ocr_text != ocr_text:
        raise ValueError("merged_state_ocr_input_changed")
    allowed = os.getenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "")
    os.environ["AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS"] = ",".join(filter(None, (allowed, project_id)))
    os.environ["AICHECK_JEV_PRIMARY_DECISION_ENABLED"] = "true"
    os.environ["AICHECK_JEV_ENABLED"] = "true"
    os.environ["AICHECK_JEV_DATA_EGRESS_APPROVED"] = "true"
    with patch.object(jev_primary, "jev_stage_enabled", return_value=True):
        question_input = jev_primary._node_inputs(
            repo.state, run, rules, project["businessPackSnapshot"], context.get("businessFacts"))
    if send and question_input["status"] != "ready":
        raise ValueError("question_author_input_not_ready:" + question_input["status"])
    if send and not jev_stage_enabled("PRIMARY_DECISION"):
        raise ValueError("jev_live_gate_disabled:" + json.dumps({
            "keyPresent": bool(os.environ.get("AICHECK_JEV_API_KEY")),
            "enabled": os.environ.get("AICHECK_JEV_ENABLED"),
            "egressApproved": os.environ.get("AICHECK_JEV_DATA_EGRESS_APPROVED"),
            "primaryEnabled": os.environ.get("AICHECK_JEV_PRIMARY_DECISION_ENABLED"),
        }))
    if send:
        # The live trial follows the graph's actual order. Qwen must author
        # every choice before any Jev call; the request cap is checked here.
        run_step(run, "qwen_compose_jev_questions", context)
        question_plan = run["jevQuestionPlan"]
        if question_plan.get("status") != "completed":
            raise ValueError("qwen_question_plan_not_ready:" + str(question_plan.get("status")))
        with patch.object(jev_primary, "ask_jev", side_effect=OSError("preflight_only")):
            preflight = jev_primary.decide_node(repo.state, run, rules,
                                                 project["businessPackSnapshot"], question_plan,
                                                 business_facts=context.get("businessFacts"))
        if preflight.get("status") != "unavailable" or preflight.get("requestBatchCount") != expected_requests:
            raise ValueError("request_count_preflight_changed:" + str(preflight.get("status"))
                             + ":" + str(preflight.get("requestBatchCount")))
        run_step(run, "jev_decision", context)
        decision = run["jevDecision"]
        if decision.get("inputHash") != preflight["inputHash"]:
            raise ValueError("live_jev_input_changed_after_preflight")
        effective = context["ruleResults"]
    else:
        question_plan = {"status": "not_run"}
        decision = {"status": "preflight_only", "requestBatchCount": None, "atomic": []}
        effective = rules
    return {"schemaVersion": "jev-primary-lab-case-v1", "projectId": project_id,
            "nodeId": node_id, "documentVersionIds": versions, "ocrCharCount": len(ocr_text),
            "questionAuthorInputStatus": question_input["status"],
            "plannedQuestionCount": len(question_input.get("checks") or []),
            "questionPlan": question_plan, "inputHash": decision.get("inputHash"),
            "actualRuleResult": rules[0].get("result"),
            "actualRuleAtomic": [{"atomicCheckId": row.get("atomicCheckId"), "result": row.get("result"),
                                  "resultRole": row.get("resultRole"),
                                  "toolNames": [tool.get("toolName") for tool in row.get("toolResults") or []]}
                                 for row in rules[0]["atomicCheckResults"]],
            "jevDecision": decision, "activeResult": effective[0].get("result"),
            "readOnly": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--node-id", required=True, type=int)
    parser.add_argument("--expected-requests", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--prompt-key", action="store_true")
    parser.add_argument("--qwen-key-from-server", action="store_true")
    args = parser.parse_args()
    if stat.S_IMODE(args.snapshot.stat().st_mode) & 0o077:
        parser.error("private_snapshot_permissions_required")
    if args.send and not args.prompt_key:
        parser.error("live replay requires --prompt-key")
    if args.qwen_key_from_server and not args.send:
        parser.error("server key retrieval requires --send")
    snapshot = json.loads(zlib.decompress(args.snapshot.read_bytes()))
    qwen_env_names = ("AICHECK_QWEN_CALL_MODE", "QWEN_API_KEY", "QWEN_API_BASE",
                      "AICHECK_LLM_API_KEY", "AICHECK_LLM_API_BASE")
    previous_qwen_env = {name: os.environ.get(name) for name in qwen_env_names}
    if args.prompt_key:
        os.environ["AICHECK_JEV_API_KEY"] = getpass.getpass("Jev test API key: ").strip()
    try:
        if args.qwen_key_from_server:
            key = _qwen_test_key_from_server()
            base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            os.environ["AICHECK_QWEN_CALL_MODE"] = "official_api"
            os.environ["QWEN_API_KEY"] = key
            os.environ["QWEN_API_BASE"] = base
            # Generic official-API settings have precedence in QwenRuntime.
            # Pin both names to the same provider for this isolated replay.
            os.environ["AICHECK_LLM_API_KEY"] = key
            os.environ["AICHECK_LLM_API_BASE"] = base
        report = replay(snapshot, args.project_id, args.node_id, send=args.send,
                        expected_requests=args.expected_requests)
        _private_write(args.output, report)
    finally:
        os.environ.pop("AICHECK_JEV_API_KEY", None)
        if args.qwen_key_from_server:
            for name, previous in previous_qwen_env.items():
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous
    print(json.dumps({"status": report["jevDecision"]["status"],
                      "nodeId": report["nodeId"], "ocrCharCount": report["ocrCharCount"],
                      "questionAuthorInputStatus": report["questionAuthorInputStatus"],
                      "plannedQuestionCount": report["plannedQuestionCount"],
                      "requestCount": report["jevDecision"].get("requestBatchCount"),
                      "actualRuleResult": report["actualRuleResult"],
                      "activeResult": report["activeResult"]}, ensure_ascii=False))
    return 0 if report["jevDecision"]["status"] in {"completed", "preflight_only"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
