"""Package full OCR and fixed node questions for blind inspector labeling.

This is a private local handoff artifact. It contains neither Jev output nor
existing document bindings, and cannot be used as an outbound Jev request.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import zlib
from pathlib import Path
from typing import Any

from scripts.run_jev_routing_evaluation import _prepared, snapshot_cases


def inspector_sources(snapshot: dict[str, Any], labels: dict[str, Any]) -> dict[str, Any]:
    if labels.get("schemaVersion") != "jev-routing-blind-label-packet-v1":
        raise ValueError("blind_routing_labels_required")
    cases = {(case["projectId"], case["documentId"], case["documentVersionId"]): case
             for case in snapshot_cases(snapshot)}
    rows = []
    for label in labels.get("cases") or []:
        identity = (label.get("projectId"), label.get("documentId"),
                    label.get("documentVersionId"))
        case = cases.get(identity)
        if case is None:
            raise ValueError("blind_case_not_in_snapshot")
        prepared = _prepared(case)
        if prepared["status"] != "ready" or prepared["inputHash"] != label.get("inputHash"):
            raise ValueError("blind_case_input_hash_changed")
        rows.append({"projectId": identity[0], "documentId": identity[1],
                     "documentVersionId": identity[2], "inputHash": prepared["inputHash"],
                     "ocrText": prepared["_state"],
                     "nodes": [{"nodeId": case["nodeIds"][key],
                                "question": question["instructions"]}
                               for key, question in case["questions"].items()]})
    return {"schemaVersion": "jev-routing-inspector-sources-v1", "caseCount": len(rows),
            "instruction": "依据完整 OCR 对每个节点独立标属于、不属于或不确定；不得参考模型或旧挂载。",
            "cases": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if any(stat.S_IMODE(path.stat().st_mode) & 0o077 for path in (args.snapshot, args.labels)):
            raise ValueError("private_input_permissions_required")
        snapshot = json.loads(zlib.decompress(args.snapshot.read_bytes()))
        labels = json.loads(args.labels.read_text(encoding="utf-8"))
        packet = inspector_sources(snapshot, labels)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(packet, output, ensure_ascii=False)
                output.write("\n")
        except BaseException:
            args.output.unlink(missing_ok=True)
            raise
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"caseCount": packet["caseCount"], "status": "ready_for_inspector"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
