"""Resume-safe, read-only paired Lab replay over a private preflight selection.

The journal contains no OCR or credentials. It records a reservation before
each outbound run; an interrupted reservation is never retried automatically.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import stat
import zlib
from pathlib import Path

from scripts.run_jev_primary_lab_case import _qwen_test_key_from_server, replay


def _append_private(path: Path, row: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        if stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o077:
            raise ValueError("private_journal_permissions_required")
        with os.fdopen(descriptor, "a", encoding="utf-8") as output:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _reserved_nodes(path: Path) -> set[int]:
    if not path.exists():
        return set()
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("private_journal_permissions_required")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {int(row["nodeId"]) for row in rows if row.get("event") == "reserved"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--limit", required=True, type=int)
    parser.add_argument("--expected-requests", type=int, default=1)
    parser.add_argument("--node-id", type=int)
    args = parser.parse_args()
    if args.limit < 1 or args.expected_requests < 1:
        parser.error("positive_limit_and_expected_requests_required")
    if stat.S_IMODE(args.snapshot.stat().st_mode) & 0o077:
        parser.error("private_snapshot_permissions_required")
    snapshot_bytes = args.snapshot.read_bytes()
    snapshot_hash = hashlib.sha256(snapshot_bytes).hexdigest()
    snapshot = json.loads(zlib.decompress(snapshot_bytes))
    preflight = json.loads(args.preflight.read_text())
    if preflight.get("snapshot") != str(args.snapshot):
        parser.error("snapshot_path_mismatch")
    selected = {}
    for row in preflight.get("results") or []:
        if row.get("status") == "ready":
            selected.setdefault(int(row["nodeId"]), row)
    completed = _reserved_nodes(args.journal)
    pending = [(node, row) for node, row in sorted(selected.items())
               if node not in completed and (args.node_id is None or node == args.node_id)][:args.limit]
    if not pending:
        print(json.dumps({"status": "no_pending_nodes", "ready": len(selected),
                          "alreadyReserved": len(completed)}))
        return 0
    jev_key = getpass.getpass("Jev test API key: ").strip()
    if not jev_key:
        parser.error("jev_test_key_required")
    qwen_key = _qwen_test_key_from_server()
    qwen_env = ("AICHECK_QWEN_CALL_MODE", "QWEN_API_KEY", "QWEN_API_BASE",
                "AICHECK_LLM_API_KEY", "AICHECK_LLM_API_BASE")
    previous = {name: os.environ.get(name) for name in qwen_env}
    base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    os.environ.update({"AICHECK_JEV_API_KEY": jev_key,
                       "AICHECK_QWEN_CALL_MODE": "official_api",
                       "QWEN_API_KEY": qwen_key, "QWEN_API_BASE": base,
                       "AICHECK_LLM_API_KEY": qwen_key, "AICHECK_LLM_API_BASE": base})
    try:
        for index, (node, row) in enumerate(pending, 1):
            project = str(row["projectId"])
            print(json.dumps({"event": "running", "index": index,
                              "batchSize": len(pending), "nodeId": node}), flush=True)
            _append_private(args.journal, {"event": "reserved", "nodeId": node,
                                           "projectId": project, "snapshotSha256": snapshot_hash,
                                           "expectedRequests": args.expected_requests})
            try:
                report = replay(snapshot, project, node, send=True,
                                expected_requests=args.expected_requests)
            except Exception as exc:  # noqa: BLE001 -- external evaluator records one failed attempt
                message = str(exc)
                safe_prefixes = ("qwen_question_plan_not_ready:",
                                 "question_author_input_not_ready:",
                                 "request_count_preflight_changed:")
                _append_private(args.journal, {"event": "error", "nodeId": node,
                                               "errorType": type(exc).__name__,
                                               "errorCode": message[:120] if isinstance(exc, ValueError)
                                               and message.startswith(safe_prefixes)
                                               else "external_or_runtime_error"})
                print(json.dumps({"event": "error", "nodeId": node,
                                  "errorType": type(exc).__name__}), flush=True)
            else:
                _append_private(args.journal, {"event": "result", "nodeId": node,
                                               "report": report})
                print(json.dumps({"event": "result", "nodeId": node,
                                  "status": report["jevDecision"]["status"],
                                  "old": report["actualRuleResult"],
                                  "new": report.get("jevOpinionResult")}), flush=True)
    finally:
        os.environ.pop("AICHECK_JEV_API_KEY", None)
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
