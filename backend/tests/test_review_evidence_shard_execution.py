from __future__ import annotations

import json

import pytest

from libs.db.repository import repo
from libs.review_orchestrator import execution as ex
from libs.review_orchestrator.shard_execution import EvidenceShardProcessingIncomplete
from libs.review_orchestrator.shard_execution import aggregate_shard_findings


def setup_function() -> None:
    repo.reset()


def _segment(shard_index: int, text: str, *, evidence_link_id: str) -> dict:
    return {
        "artifactSegmentId": f"ESEG-{shard_index}",
        "artifactId": f"EART-{shard_index}",
        "artifactType": "evidenceLink",
        "documentVersionId": f"DV-{shard_index}",
        "sourceId": evidence_link_id,
        "segmentIndex": 0,
        "segmentCount": 1,
        "segmentKind": "complete",
        "payloadSlice": {
            "id": evidence_link_id,
            "documentVersionId": f"DV-{shard_index}",
            "pageNo": 1,
            "bbox": [1, 2, 30, 40],
            "quotedText": text,
        },
    }


def _package() -> tuple[dict, list[dict]]:
    manifest = {
        "id": "EMAN-1",
        "evidenceManifestId": "EMAN-1",
        "evidenceSnapshotId": "ESNAP-1",
        "projectId": "P-1",
        "nodeId": 1,
        "artifacts": [
            {
                "artifactId": "EART-1",
                "artifactType": "evidenceLink",
                "documentVersionId": "DV-1",
                "sourceId": "EL-1",
            },
            {
                "artifactId": "EART-2",
                "artifactType": "evidenceLink",
                "documentVersionId": "DV-2",
                "sourceId": "EL-2",
            },
        ],
    }
    shards = [
        {
            "id": f"ESHARD-{index}",
            "evidenceShardId": f"ESHARD-{index}",
            "evidenceManifestId": "EMAN-1",
            "evidenceSnapshotId": "ESNAP-1",
            "reviewRunId": "RRUN-SHARDS",
            "projectId": "P-1",
            "nodeId": 1,
            "shardIndex": index,
            "status": "pending",
            "artifactIds": [f"EART-{index}"],
            "artifactSegments": [
                _segment(
                    index,
                    "设计许可证TS1844171-2028" if index == 1 else "施工图压力管道级别GC2",
                    evidence_link_id=f"EL-{index}",
                )
            ],
        }
        for index in (1, 2)
    ]
    return manifest, shards


def _review_run() -> dict:
    return {
        "reviewRunId": "RRUN-SHARDS",
        "aiRunId": "AIRUN-SHARDS",
        "projectId": "P-1",
        "nodeId": 1,
        "modelAlias": "review-chat",
        "promptVersion": "prompt-v1",
        "agentId": "agent",
        "agentVersion": "1",
        "reviewMode": "gap_precheck",
        "advisoryOnly": True,
        "evidenceManifestId": "EMAN-1",
        "evidenceShardIds": ["ESHARD-1", "ESHARD-2"],
        "modelCallAttemptIds": [],
    }


def _context() -> dict:
    return {
        "promptShape": {"messagesHash": "sha256:full-prompt"},
        "groundingInput": {
            "groundingStatus": "grounded",
            "documentVersionIds": ["DV-1", "DV-2"],
            "evidenceLinks": [],
            "evidenceTextCorpus": ["设计许可证TS1844171-2028", "施工图压力管道级别GC2"],
        },
        "evidenceLinks": [],
        "ruleResults": [],
        "retrievalTraces": [],
        "auditRuntime": {"mode": "ocr_llm"},
    }


def _install_package() -> tuple[dict, list[dict]]:
    manifest, shards = _package()
    repo.state["evidence_manifests"] = [manifest]
    repo.state["evidence_shards"] = shards
    return manifest, shards


def test_deterministic_review_processes_every_shard_and_deduplicates_the_node_finding(
    monkeypatch,
) -> None:
    manifest, shards = _install_package()
    review_run = _review_run()
    monkeypatch.setattr(ex, "review_llm_execution_mode", lambda: "deterministic")

    drafts, metadata = ex.generate_finding_drafts(review_run, _context())

    assert len(drafts) == 1
    assert metadata["processedShardCount"] == 2
    assert all(shard["status"] == "completed" for shard in shards)
    assert all(shard["processingMode"] == "deterministic" for shard in shards)
    assert all(shard["processedInputHash"] for shard in shards)
    assert review_run["evidenceCoverage"]["coveragePassed"] is True
    assert review_run["nodeFindingAggregate"]["sourceEvidenceShardIds"] == [
        "ESHARD-1",
        "ESHARD-2",
    ]
    assert review_run["nodeFindingAggregate"]["findingDrafts"] == drafts
    assert repo.state["node_finding_aggregates"] == [
        review_run["nodeFindingAggregate"]
    ]
    assert manifest["evidenceManifestId"] == "EMAN-1"


def test_model_review_calls_once_per_shard_and_records_bidirectional_lineage(
    monkeypatch,
) -> None:
    _manifest, shards = _install_package()
    review_run = _review_run()
    seen_prompts: list[str] = []

    class FakeRuntime:
        def chat_sync(self, messages, **kwargs):
            text = str(messages[0]["content"])
            seen_prompts.append(text)
            shard_index = 1 if "TS1844171-2028" in text else 2
            return {
                "id": f"RESP-{shard_index}",
                "model": "review-chat",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "findings": [
                                        {
                                            "findingType": f"shard_{shard_index}_review",
                                            "severity": "medium",
                                            "title": f"分片 {shard_index} 待人工确认",
                                            "description": f"分片 {shard_index} 资料需要人工核对。",
                                            "evidenceRefs": [],
                                            "ruleRefs": [],
                                            "kbRefs": [],
                                            "confidence": 0.5,
                                            "suggestedAction": "human_confirm",
                                            "groundingStatus": "insufficient_evidence",
                                            "unsupportedClaims": [],
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ],
                "usage": {"input_tokens": 100, "output_tokens": 20},
            }

    monkeypatch.setattr(ex, "review_llm_execution_mode", lambda: "litellm")
    monkeypatch.setattr(
        ex,
        "build_review_messages",
        lambda _run, context: [
            {
                "role": "user",
                "content": "|".join(context["groundingInput"]["evidenceTextCorpus"]),
            }
        ],
    )
    monkeypatch.setattr(ex, "build_review_prompt_shape", lambda _run, _context: {})
    monkeypatch.setattr(ex, "qwen_runtime_public_config", lambda: {"provider": "test"})
    monkeypatch.setattr(ex, "qwen_runtime_client", lambda: FakeRuntime())
    monkeypatch.setattr(ex, "model_cost_cny", lambda _usage: {"total": 0.0})

    drafts, metadata = ex.generate_finding_drafts(review_run, _context())

    assert len(seen_prompts) == 2
    assert "TS1844171-2028" in seen_prompts[0]
    assert "GC2" not in seen_prompts[0]
    assert "GC2" in seen_prompts[1]
    assert "TS1844171-2028" not in seen_prompts[1]
    assert {draft["findingType"] for draft in drafts} == {
        "shard_1_review",
        "shard_2_review",
    }
    attempts = [
        row
        for row in repo.state["model_call_attempts"]
        if row.get("reviewRunId") == "RRUN-SHARDS"
    ]
    assert {row["evidenceShardId"] for row in attempts} == {"ESHARD-1", "ESHARD-2"}
    assert all(row["logicalCallId"].endswith(row["evidenceShardId"]) for row in attempts)
    assert all(len(shard["modelAttemptIds"]) == 1 for shard in shards)
    assert {item for shard in shards for item in shard["modelAttemptIds"]} == {
        row["id"] for row in attempts
    }
    assert metadata["processedShardCount"] == 2
    assert review_run["nodeFindingAggregate"]["sourceModelAttemptIds"] == sorted(
        row["id"] for row in attempts
    )


def test_model_failure_keeps_completed_sibling_and_marks_processing_incomplete(
    monkeypatch,
) -> None:
    _manifest, shards = _install_package()
    review_run = _review_run()
    call_count = 0

    class FailingSecondRuntime:
        def chat_sync(self, messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("provider unavailable")
            return {
                "id": "RESP-1",
                "model": "review-chat",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "findings": [
                                        {
                                            "findingType": "license_review",
                                            "severity": "medium",
                                            "title": "许可证待人工确认",
                                            "description": "许可证资料需要人工核对。",
                                            "evidenceRefs": [],
                                            "ruleRefs": [],
                                            "kbRefs": [],
                                            "confidence": 0.5,
                                            "suggestedAction": "human_confirm",
                                            "groundingStatus": "insufficient_evidence",
                                            "unsupportedClaims": [],
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ],
                "usage": {"input_tokens": 100, "output_tokens": 20},
            }

    monkeypatch.setattr(ex, "review_llm_execution_mode", lambda: "litellm")
    monkeypatch.setattr(
        ex,
        "build_review_messages",
        lambda _run, context: [
            {"role": "user", "content": "|".join(context["groundingInput"]["evidenceTextCorpus"])}
        ],
    )
    monkeypatch.setattr(ex, "build_review_prompt_shape", lambda _run, _context: {})
    monkeypatch.setattr(ex, "qwen_runtime_public_config", lambda: {"provider": "test"})
    monkeypatch.setattr(ex, "qwen_runtime_client", lambda: FailingSecondRuntime())
    monkeypatch.setattr(ex, "model_cost_cny", lambda _usage: {"total": 0.0})

    with pytest.raises(EvidenceShardProcessingIncomplete) as error:
        ex.generate_finding_drafts(review_run, _context())

    assert error.value.failed_shard_ids == ["ESHARD-2"]
    assert shards[0]["status"] == "completed"
    assert shards[0]["findingDrafts"]
    assert shards[1]["status"] == "failed"
    assert shards[1]["failureReason"] == "RuntimeError"
    assert shards[1]["modelAttemptIds"]
    assert review_run["evidenceCoverage"]["coveragePassed"] is False
    aggregate_finding = review_run["nodeFindingAggregate"]["findingDrafts"][0]
    assert aggregate_finding["findingType"] == "license_review"
    assert aggregate_finding["sourceEvidenceShardIds"] == ["ESHARD-1"]


def test_review_run_exposes_review_incomplete_without_changing_business_status(
    monkeypatch,
) -> None:
    review_run = {
        **_review_run(),
        "id": "RRUN-SHARDS",
        "status": "queued",
        "evidenceShardIds": [],
        "advisoryOnly": True,
    }
    repo.state["review_runs"] = [review_run]

    def fail_graph(*args, **kwargs):
        raise EvidenceShardProcessingIncomplete(["ESHARD-2"])

    monkeypatch.setattr(
        "libs.review_orchestrator.graph.execute_review_graph",
        fail_graph,
    )

    result = ex.execute_review_run_inline("RRUN-SHARDS")

    assert result["status"] == "review_incomplete"
    assert result["failedEvidenceShardIds"] == ["ESHARD-2"]
    assert review_run["status"] == "review_incomplete"
    assert review_run["currentStep"] == "review_incomplete"
    assert review_run["retryableFailure"] is True


def test_aggregate_merges_exact_duplicates_but_preserves_conflicting_findings() -> None:
    common = {
        "id": "FND-1",
        "findingType": "license_scope",
        "severity": "medium",
        "title": "许可范围核查",
        "description": "现有资料不足，需人工核查许可范围。",
        "suggestedAction": "human_confirm",
        "evidenceRefs": [{"evidenceLinkId": "EL-1"}],
        "ruleRefs": [],
        "kbRefs": [],
    }
    aggregate = aggregate_shard_findings(
        _review_run(),
        [
            {
                "evidenceShardId": "ESHARD-1",
                "modelAttemptIds": ["MCALL-1"],
                "findingDrafts": [common],
            },
            {
                "evidenceShardId": "ESHARD-2",
                "modelAttemptIds": ["MCALL-2"],
                "findingDrafts": [
                    {
                        **common,
                        "id": "FND-2",
                        "evidenceRefs": [{"evidenceLinkId": "EL-2"}],
                    },
                    {
                        **common,
                        "id": "FND-3",
                        "description": "许可范围已经覆盖本项目。",
                        "suggestedAction": "request_correction",
                    },
                ],
            },
        ],
    )

    assert len(aggregate["findingDrafts"]) == 2
    merged = next(
        row
        for row in aggregate["findingDrafts"]
        if row["description"] == common["description"]
    )
    assert {row["evidenceLinkId"] for row in merged["evidenceRefs"]} == {
        "EL-1",
        "EL-2",
    }
    assert merged["sourceEvidenceShardIds"] == ["ESHARD-1", "ESHARD-2"]
    assert aggregate["conflicts"] == [
        {
            "findingType": "license_scope",
            "title": "许可范围核查",
            "findingIds": ["FND-1", "FND-3"],
            "sourceEvidenceShardIds": ["ESHARD-1", "ESHARD-2"],
            "requiresHumanConfirmation": True,
        }
    ]
