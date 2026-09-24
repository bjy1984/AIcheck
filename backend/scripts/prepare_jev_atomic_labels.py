"""Produce a blind inspector packet from the new 16+17 Jev risk sample."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
from typing import Any

from scripts.evaluate_jev_atomic_opinions import candidates_from_state, r19_candidates_from_state


def blind_packet(state: dict[str, Any], *, comparison: str = "rule_engine") -> dict[str, Any]:
    if comparison not in {"rule_engine", "r19"}:
        raise ValueError("unknown_comparison")
    candidates = (r19_candidates_from_state(state) if comparison == "r19"
                  else candidates_from_state(state))
    rows = [{"caseId": row["caseId"], "reviewRunId": row["reviewRunId"],
             "projectId": row["projectId"], "nodeId": row["nodeId"],
             "atomicCheckId": row["atomicCheckId"], "inputHash": row["inputHash"],
             "documentVersionIds": row["documentVersionIds"], "instruction": row["instruction"],
             "labelSource": "inspector", "annotatedBy": "", "choice": None}
            for row in candidates["candidates"]]
    return {"schemaVersion": "jev-atomic-blind-label-packet-v1", "comparisonSource": comparison,
            "status": candidates["status"],
            "selectedDisagreementCount": candidates.get("selectedDisagreementCount"),
            "selectedJevPassedCount": candidates.get("selectedJevPassedCount"), "cases": rows}


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
    parser.add_argument("--snapshot", required=True, type=Path,
                        help="Private OCR-free result from run_jev_atomic_evaluation")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--comparison", choices=("rule_engine", "r19"), default="rule_engine")
    args = parser.parse_args()
    try:
        if stat.S_IMODE(args.snapshot.stat().st_mode) & 0o077:
            raise ValueError("private_snapshot_permissions_required")
        packet = blind_packet(json.loads(args.snapshot.read_text(encoding="utf-8")),
                              comparison=args.comparison)
        _private_write(args.output, packet)
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: value for key, value in packet.items() if key != "cases"}, ensure_ascii=False))
    return 0 if packet["status"] == "ready_for_inspector" else 2


if __name__ == "__main__":
    raise SystemExit(main())
