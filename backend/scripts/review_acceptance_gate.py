"""Validate retained, source-bound business acceptance evidence before binding publication.

Artifact hashes establish consistency, not reviewer authenticity or independent business truth.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from libs.review_tools.executor import aggregate_atomic_results, is_evidence_gate_plan

STATES = {
    "compliant": "passed",
    "noncompliant": "failed",
    "insufficient": "evidence_insufficient",
    "not_applicable": "not_applicable",
}


def source_digest(backend: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        path
        for folder in ("libs", "apps", "scripts", "business_packs")
        for path in (backend / folder).rglob("*")
        if path.is_file() and path.suffix in {".py", ".yaml", ".yml", ".json", ".md", ".txt"}
    )
    files = sorted(
        set(files)
        | {
            path
            for pattern in ("requirements*.txt", "pyproject.toml", "*.lock")
            for path in backend.glob(pattern)
            if path.is_file()
        }
    )
    for path in files:
        digest.update(
            path.relative_to(backend).as_posix().encode()
            + b"\0"
            + hashlib.sha256(path.read_bytes()).digest()
        )
    return digest.hexdigest()


def _artifact(root: Path, reference: Any) -> dict[str, Any]:
    if (
        not isinstance(reference, dict)
        or not isinstance(reference.get("path"), str)
        or not reference["path"]
    ):
        raise ValueError("acceptance_artifact_reference_missing")
    path = (root / reference["path"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("acceptance_artifact_outside_root_or_missing")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != reference.get("sha256"):
        raise ValueError("acceptance_artifact_hash_mismatch")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise TypeError("acceptance_artifact_not_object")
    return value


def canonical_input_hash(value: dict[str, Any]) -> str:
    """Hash the retained JSON input, independently of the application's inputHash."""
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _located(ref: Any, versions: list[str]) -> bool:
    if (
        not isinstance(ref, dict)
        or ref.get("documentVersionId") not in versions
        or type(ref.get("pageNo")) is not int
        or ref["pageNo"] <= 0
    ):
        return False
    quote = ref.get("quotedText")
    bbox = ref.get("bbox")
    return (isinstance(quote, str) and bool(quote.strip())) or (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(type(value) in (int, float) and math.isfinite(value) for value in bbox)
        and bbox[0] >= 0
        and bbox[1] >= 0
        and bbox[2] > bbox[0]
        and bbox[3] > bbox[1]
    )


def validate_acceptance(
    path: Path, pack: dict[str, Any], *, binding_sha256: str, code_sha256: str
) -> dict[str, Any]:
    manifest_bytes = path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schemaVersion") != "review-business-acceptance-v1"
    ):
        raise ValueError("acceptance_schema_invalid")
    if (
        manifest.get("bindingSha256") != binding_sha256
        or manifest.get("sourceSha256") != code_sha256
    ):
        raise ValueError("acceptance_evidence_stale")
    expected: dict[str, set[str]] = {}
    bindings = {}
    for item in pack["atomicCheckToolBindings"]:
        if item["atomicCheckId"] in bindings:
            raise ValueError("acceptance_binding_duplicate")
        bindings[item["atomicCheckId"]] = item
        expected.setdefault(item["sourceRuleId"], set()).add(item["atomicCheckId"])
    if not expected:
        raise ValueError("acceptance_bindings_empty")
    records = manifest.get("scenarios")
    if not isinstance(records, list):
        raise TypeError("acceptance_scenarios_missing")
    seen = set()
    artifacts = set()
    for record in records:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("ruleId"), str)
            or not isinstance(record.get("scenario"), str)
        ):
            raise TypeError("acceptance_scenario_identity_missing")
        rule, scenario = record["ruleId"], record["scenario"]
        key = rule, scenario
        if rule not in expected or scenario not in STATES or key in seen:
            raise ValueError("acceptance_scenario_unknown_or_duplicate")
        seen.add(key)
        if (
            record.get("status") != "passed"
            or not isinstance(record.get("reviewer"), str)
            or not record["reviewer"].strip()
        ):
            raise ValueError("acceptance_scenario_not_reviewed_and_passed")
        fixture, output = (
            _artifact(path.parent, record.get(field)) for field in ("fixture", "output")
        )
        pair = record["fixture"]["sha256"], record["output"]["sha256"]
        if pair in artifacts:
            raise ValueError("acceptance_artifacts_reused")
        artifacts.add(pair)
        if (
            fixture.get("ruleId") != rule
            or fixture.get("expectedResult") != STATES[scenario]
            or output.get("ruleId") != rule
            or output.get("result") != STATES[scenario]
        ):
            raise ValueError("acceptance_observed_result_mismatch")
        frozen_input = fixture.get("frozenInput")
        if not isinstance(frozen_input, dict):
            raise TypeError("acceptance_frozen_input_missing")
        frozen_hash = canonical_input_hash(frozen_input)
        if (
            fixture.get("fixtureInputSha256") != frozen_hash
            or output.get("fixtureInputSha256") != frozen_hash
        ):
            raise ValueError("acceptance_frozen_input_mismatch")
        if (
            output.get("bindingSha256") != binding_sha256
            or output.get("sourceSha256") != code_sha256
        ):
            raise ValueError("acceptance_output_stale")
        atomics = output.get("atomicResults")
        if not isinstance(atomics, list) or any(
            not isinstance(row, dict)
            or not isinstance(row.get("atomicCheckId"), str)
            or row.get("result") not in STATES.values()
            for row in atomics
        ):
            raise ValueError("acceptance_atomic_results_invalid")
        ids = [row["atomicCheckId"] for row in atomics]
        if len(ids) != len(set(ids)) or set(ids) != expected[rule]:
            raise ValueError("acceptance_atomic_coverage_incomplete")
        normalized = [
            {
                "result": row["result"],
                "resultRole": "evidence_gate"
                if is_evidence_gate_plan(bindings[row["atomicCheckId"]])
                else "decision",
            }
            for row in atomics
        ]
        if aggregate_atomic_results(normalized) != output["result"]:
            raise ValueError("acceptance_atomic_aggregate_mismatch")
        versions = frozen_input.get("inputDocumentVersionIds")
        if (
            not isinstance(versions, list)
            or (not versions and scenario != "insufficient")
            or any(not isinstance(value, str) or not value.strip() for value in versions)
        ):
            raise ValueError("acceptance_document_fixture_missing")
        refs = output.get("evidenceRefs", [])
        if (
            not isinstance(refs, list)
            or (scenario != "insufficient" and not refs)
            or any(not _located(ref, versions) for ref in refs)
        ):
            raise ValueError("acceptance_evidence_location_missing")
    if seen != {(rule, scenario) for rule in expected for scenario in STATES}:
        raise ValueError("acceptance_four_scenarios_incomplete")
    return {
        "acceptedRuleCount": len(expected),
        "acceptedScenarioCount": len(seen),
        "acceptanceManifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "acceptanceSourceSha256": code_sha256,
    }
