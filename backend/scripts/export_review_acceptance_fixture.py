"""Freeze a real ReviewRun into a replayable acceptance fixture.

This script never writes a verdict of its own. `expectedResult` is copied from
the result the run actually recorded in `rule_check_results`, and the fixture is
replayed end to end before it is offered as evidence. A replay that does not
reproduce the recorded result means the frozen input is not what the run saw, so
the fixture is wrong even though the run was fine: the artifacts are still
written (they document the divergence) but the exit code is non-zero and
`provenance.json` records that the replay disagreed. Do not cite such a
directory as acceptance evidence.

Business acceptance stays `not_reviewed` and no reviewer is filled in: agreement
between a run and its replay is a determinism check, not a human sign-off.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS

if __package__:
    from .replay_review_acceptance import export_replay
    from .review_acceptance_gate import STATES, canonical_input_hash
else:
    from replay_review_acceptance import export_replay
    from review_acceptance_gate import STATES, canonical_input_hash

SCENARIOS = {value: key for key, value in STATES.items()}


def find_review_run(state: dict[str, Any], review_run_id: str) -> dict[str, Any]:
    matches = [
        row
        for row in state.get("review_runs") or []
        if isinstance(row, dict) and row.get("reviewRunId") == review_run_id
    ]
    if len(matches) != 1:
        raise ValueError("export_review_run_not_found_or_ambiguous")
    return matches[0]


def recorded_result(state: dict[str, Any], review_run_id: str) -> str:
    """The result the run itself produced; the fixture may not invent another one."""
    results = {
        str(row.get("result"))
        for row in state.get("rule_check_results") or []
        if isinstance(row, dict) and row.get("reviewRunId") == review_run_id
    }
    if not results:
        raise ValueError("export_run_has_no_recorded_result")
    if len(results) > 1:
        # A node with disagreeing rule results has no single scenario to freeze.
        raise ValueError("export_run_results_conflict:" + ",".join(sorted(results)))
    result = results.pop()
    if result not in SCENARIOS:
        # execution_error / human_review_required are not acceptance scenarios.
        raise ValueError("export_run_result_not_an_acceptance_scenario:" + result)
    return result


def build_fixture(state: dict[str, Any], review_run_id: str) -> dict[str, Any]:
    run = find_review_run(state, review_run_id)
    node = run.get("nodeId")
    node = int(node) if type(node) in (int, str) and str(node).isdigit() else None
    if node not in NDT_FACT_BUILDERS:
        raise ValueError("export_fact_builder_not_supported")
    # The scope must be the one frozen when the run executed. Re-freezing it now
    # would describe today's documents, not the ones the run actually read.
    if not isinstance(run.get("documentScopeSnapshot"), dict):
        raise TypeError("export_run_has_no_frozen_document_scope")
    versions = run.get("inputDocumentVersionIds")
    if not isinstance(versions, list):
        raise TypeError("export_run_document_scope_missing")
    frozen = {
        "state": deepcopy(state),
        "reviewRun": deepcopy(run),
        "inputDocumentVersionIds": deepcopy(versions),
    }
    return {
        "ruleId": f"R{node:02d}",
        "expectedResult": recorded_result(state, review_run_id),
        "frozenInput": frozen,
        "fixtureInputSha256": canonical_input_hash(frozen),
    }


def export_run(
    state: dict[str, Any],
    review_run_id: str,
    output_dir: Path,
    *,
    pack_id: str = "engineering_inspection_v1",
) -> dict[str, Any]:
    fixture = build_fixture(state, review_run_id)
    body = (json.dumps(fixture, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory() as scratch:
        staged = Path(scratch) / "fixture.json"
        staged.write_bytes(body)
        report = export_replay(staged, output_dir, pack_id=pack_id)
    run = find_review_run(state, review_run_id)
    provenance = {
        "schemaVersion": "review-acceptance-provenance-v1",
        "reviewRunId": review_run_id,
        "projectId": run.get("projectId"),
        "nodeId": run.get("nodeId"),
        "ruleId": report["ruleId"],
        "scenario": SCENARIOS[fixture["expectedResult"]],
        "recordedResult": fixture["expectedResult"],
        "replayReproducedRecordedResult": report["matchesExpected"],
        "documentScopeSnapshotHash": run["documentScopeSnapshot"].get("snapshotHash"),
        "businessAcceptance": "not_reviewed",
    }
    (output_dir / "provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n"
    )
    return {**report, "provenance": provenance}


def load_run_scope(review_run_id: str) -> dict[str, Any]:
    from libs.db import repository

    repository.load_review_run_state(review_run_id)
    return repository.repo.state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pack-id", default="engineering_inspection_v1")
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Read a previously captured state snapshot instead of the live database.",
    )
    args = parser.parse_args()
    state = (
        json.loads(args.state_file.read_text())
        if args.state_file
        else load_run_scope(args.review_run_id)
    )
    report = export_run(state, args.review_run_id, args.output_dir, pack_id=args.pack_id)
    print(json.dumps(report, ensure_ascii=False))
    # A replay that does not reproduce the recorded result is a broken fixture.
    return 0 if report["matchesExpected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
