"""Synthetic acceptance artifacts are temporary test data, never release approval."""

import hashlib
import json

import pytest
import yaml

from scripts import publish_atomic_check_bindings as publisher
from scripts.review_acceptance_gate import (
    STATES,
    canonical_input_hash,
    source_digest,
    validate_acceptance,
)

BINDING = "b" * 64
CODE = "c" * 64
PACK = {
    "atomicCheckToolBindings": [
        {"sourceRuleId": "R01", "atomicCheckId": "AC-1", "tools": []},
        {
            "sourceRuleId": "R01",
            "atomicCheckId": "AC-2",
            "tools": ["validate_evidence_grounding"],
            "parameters": {"resultRole": "evidence_gate"},
        },
    ]
}


def write_json(path, value):
    data = json.dumps(value).encode()
    path.write_bytes(data)
    return {"path": path.name, "sha256": hashlib.sha256(data).hexdigest()}


def bundle(root, binding=BINDING, code=CODE):
    records = []
    for scenario, result in STATES.items():
        frozen = {
            "inputDocumentVersionIds": [] if scenario == "insufficient" else ["v1"],
            "case": scenario,
        }
        digest = canonical_input_hash(frozen)
        fixture = {
            "ruleId": "R01",
            "expectedResult": result,
            "frozenInput": frozen,
            "fixtureInputSha256": digest,
        }
        output = {
            "ruleId": "R01",
            "result": result,
            "fixtureInputSha256": digest,
            "bindingSha256": binding,
            "sourceSha256": code,
            "atomicResults": [
                {"atomicCheckId": "AC-1", "result": result},
                {"atomicCheckId": "AC-2", "result": "passed"},
            ],
            "evidenceRefs": []
            if scenario == "insufficient"
            else [{"documentVersionId": "v1", "pageNo": 1, "bbox": [0, 0, 10, 10]}],
        }
        records.append(
            {
                "ruleId": "R01",
                "scenario": scenario,
                "status": "passed",
                "reviewer": "synthetic-test-only",
                "fixture": write_json(root / (scenario + "-input.json"), fixture),
                "output": write_json(root / (scenario + "-output.json"), output),
            }
        )
    manifest = {
        "schemaVersion": "review-business-acceptance-v1",
        "bindingSha256": binding,
        "sourceSha256": code,
        "scenarios": records,
    }
    path = root / "manifest.json"
    write_json(path, manifest)
    return path, manifest


def check(path):
    return validate_acceptance(path, PACK, binding_sha256=BINDING, code_sha256=CODE)


def test_accepts_complete_four_states_with_bbox_and_empty_missing_input(tmp_path):
    path, _ = bundle(tmp_path)
    result = check(path)
    assert result["acceptedRuleCount"] == 1
    assert result["acceptedScenarioCount"] == 4
    assert result["acceptanceManifestSha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda m: m["scenarios"].pop(), "four_scenarios_incomplete"),
        (lambda m: m["scenarios"].append(m["scenarios"][0]), "unknown_or_duplicate"),
        (lambda m: m.update(sourceSha256="stale"), "evidence_stale"),
        (lambda m: m["scenarios"][0].update(reviewer=" "), "not_reviewed"),
    ],
)
def test_manifest_rejections(tmp_path, mutation, error):
    path, manifest = bundle(tmp_path)
    mutation(manifest)
    write_json(path, manifest)
    with pytest.raises(ValueError, match=error):
        check(path)


@pytest.mark.parametrize(
    ("field", "mutation", "error"),
    [
        ("fixture", lambda v: v["frozenInput"].update(case="changed"), "frozen_input_mismatch"),
        ("output", lambda v: v.update(sourceSha256="stale"), "output_stale"),
        ("output", lambda v: v["atomicResults"].pop(), "atomic_coverage_incomplete"),
        (
            "output",
            lambda v: v["atomicResults"].append(v["atomicResults"][0]),
            "atomic_coverage_incomplete",
        ),
        ("output", lambda v: v["atomicResults"][0].update(result="failed"), "aggregate_mismatch"),
        (
            "output",
            lambda v: v["atomicResults"][0].update(
                result="not_applicable", resultRole="evidence_gate"
            ),
            "aggregate_mismatch",
        ),
        (
            "output",
            lambda v: v["evidenceRefs"][0].update(documentVersionId="other"),
            "evidence_location",
        ),
        ("output", lambda v: v["evidenceRefs"][0].update(pageNo=True), "evidence_location"),
        ("output", lambda v: v["evidenceRefs"][0].update(bbox=[0, 0, 0, 0]), "evidence_location"),
    ],
)
def test_rehashed_artifact_cannot_hide_inconsistent_content(tmp_path, field, mutation, error):
    path, manifest = bundle(tmp_path)
    ref = manifest["scenarios"][0][field]
    artifact = tmp_path / ref["path"]
    value = json.loads(artifact.read_bytes())
    mutation(value)
    manifest["scenarios"][0][field] = write_json(artifact, value)
    write_json(path, manifest)
    with pytest.raises(ValueError, match=error):
        check(path)


def test_tampered_artifact_rejected(tmp_path):
    path, manifest = bundle(tmp_path)
    (tmp_path / manifest["scenarios"][0]["output"]["path"]).write_text("{}")
    with pytest.raises(ValueError, match="artifact_hash_mismatch"):
        check(path)


def test_artifact_cannot_escape_root_through_symlink(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    path, manifest = bundle(root)
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    link = root / "link.json"
    link.symlink_to(outside)
    manifest["scenarios"][0]["fixture"] = {
        "path": link.name,
        "sha256": hashlib.sha256(b"{}").hexdigest(),
    }
    write_json(path, manifest)
    with pytest.raises(ValueError, match="outside_root"):
        check(path)


def test_empty_pack_cannot_be_accepted(tmp_path):
    path, _ = bundle(tmp_path)
    with pytest.raises(ValueError, match="bindings_empty"):
        validate_acceptance(
            path, {"atomicCheckToolBindings": []}, binding_sha256=BINDING, code_sha256=CODE
        )


def test_source_digest_tracks_dependencies_and_ignores_bytecode(tmp_path):
    before = source_digest(tmp_path)
    (tmp_path / "requirements.txt").write_text("dependency==1")
    after = source_digest(tmp_path)
    assert after != before
    (tmp_path / "libs").mkdir()
    (tmp_path / "libs" / "cache.pyc").write_bytes(b"cache")
    assert source_digest(tmp_path) == after


def publication_fixture(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    backend.mkdir()
    source = backend / "bindings.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "atomicCheckToolBindingSet": {
                    "version": "old",
                    "lifecycleStatus": "draft",
                    "pilotRules": ["R01"],
                }
            }
        )
    )
    binding = hashlib.sha256(source.read_bytes()).hexdigest()
    code = source_digest(backend)
    path, manifest = bundle(tmp_path, binding, code)
    monkeypatch.setattr(publisher, "BACKEND_ROOT", backend)
    monkeypatch.setattr(publisher, "binding_path", lambda _: source)
    monkeypatch.setattr(publisher, "load_business_pack", lambda _: PACK)
    monkeypatch.setattr(publisher, "validate_release", lambda _: {"bindingCount": 2})
    kwargs = {
        "approver": "synthetic-test-only",
        "approval_ticket": "test-only",
        "expected_sha256": binding,
        "dry_run": False,
        "acceptance_manifest": path,
        "release_version": "new",
    }
    return source, path, manifest, kwargs


def test_publish_dry_run_and_write_preserve_pilot_and_acceptance(tmp_path, monkeypatch):
    source, _, _, kwargs = publication_fixture(tmp_path, monkeypatch)
    before = source.read_bytes()
    assert publisher.publish("test", **{**kwargs, "dry_run": True})["dryRun"]
    assert source.read_bytes() == before
    result = publisher.publish("test", **kwargs)
    assert result["acceptedScenarioCount"] == 4
    binding = yaml.safe_load(source.read_bytes())["atomicCheckToolBindingSet"]
    assert binding["version"] == "new" and binding["lifecycleStatus"] == "published"
    assert binding["pilotRules"] == binding["rollbackPilotRules"] == ["R01"]


def test_incomplete_acceptance_prevents_publication_write(tmp_path, monkeypatch):
    source, path, manifest, kwargs = publication_fixture(tmp_path, monkeypatch)
    before = source.read_bytes()
    manifest["scenarios"].pop()
    write_json(path, manifest)
    with pytest.raises(ValueError, match="four_scenarios_incomplete"):
        publisher.publish("test", **kwargs)
    assert source.read_bytes() == before


def test_source_change_during_validation_is_not_overwritten(tmp_path, monkeypatch):
    source, _, _, kwargs = publication_fixture(tmp_path, monkeypatch)
    original = publisher.validate_acceptance

    def racing(*args, **params):
        result = original(*args, **params)
        source.write_text("concurrent update")
        return result

    monkeypatch.setattr(publisher, "validate_acceptance", racing)
    with pytest.raises(RuntimeError, match="sources changed"):
        publisher.publish("test", **kwargs)
    assert source.read_text() == "concurrent update"
    assert list(source.parent.glob("bindings.yaml*")) == [source]
