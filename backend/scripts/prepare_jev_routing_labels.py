"""Make a blind, private inspector packet from the approved seven-project snapshot.

Four eligible documents per project are selected before seeing Jev answers.
Every active node needs an independent belongs/does_not_belong/uncertain label.
The packet contains no Jev choice, confidence, or existing document binding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.run_jev_routing_evaluation import _prepared, snapshot_cases

SAMPLE_SEED = "jev-routing-blind-v1"


def blind_packet(cases: list[dict[str, Any]], *, per_project: int = 4) -> dict[str, Any]:
    if per_project < 1:
        raise ValueError("positive_project_sample_required")
    by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
    status_counts: dict[str, int] = defaultdict(int)
    for case in cases:
        row = _prepared(case)
        status = row["status"]
        if status == "ready" and case["overlongNodeIds"]:
            status = "partial_templates"
        status_counts[status] += 1
        if status != "ready":
            continue
        by_project[case["projectId"]].append({
            "projectId": case["projectId"], "documentId": case["documentId"],
            "documentVersionId": case["documentVersionId"], "inputHash": row["inputHash"],
            "labelSource": "inspector", "annotatedBy": "",
            "expectedNodeIds": sorted(set(case["nodeIds"].values())),
            "nodeLabels": [{"nodeId": node_id, "choice": None}
                           for node_id in sorted(set(case["nodeIds"].values()))],
        })
    selected = []
    for project_id in sorted({case["projectId"] for case in cases}):
        rows = by_project.get(project_id, [])
        rows.sort(key=lambda row: hashlib.sha256(
            f"{SAMPLE_SEED}/{row['projectId']}/{row['documentId']}/{row['documentVersionId']}".encode(),
        ).hexdigest())
        selected.extend(rows[:per_project])
    counts = {project_id: sum(row["projectId"] == project_id for row in selected)
              for project_id in sorted({case["projectId"] for case in cases})}
    return {"schemaVersion": "jev-routing-blind-label-packet-v1", "seed": SAMPLE_SEED,
            "status": "ready_for_inspector" if all(count == per_project for count in counts.values())
            else "insufficient_eligible_documents",
            "selectedPerProject": counts, "eligibleStatusCounts": dict(sorted(status_counts.items())),
            "labelPairCount": sum(len(row["nodeLabels"]) for row in selected), "cases": selected}


def _private_write(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if stat.S_IMODE(args.snapshot.stat().st_mode) & 0o077:
            raise ValueError("private_snapshot_permissions_required")
        cases = snapshot_cases(json.loads(zlib.decompress(args.snapshot.read_bytes())))
        packet = blind_packet(cases)
        _private_write(args.output, packet)
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: value for key, value in packet.items() if key != "cases"}, ensure_ascii=False))
    return 0 if packet["status"] == "ready_for_inspector" else 2


if __name__ == "__main__":
    raise SystemExit(main())
