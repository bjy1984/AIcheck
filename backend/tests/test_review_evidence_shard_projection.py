from __future__ import annotations


def _segment(
    *,
    artifact_id: str,
    artifact_type: str,
    source_id: str,
    payload: dict,
    segment_index: int = 0,
    segment_count: int = 1,
) -> dict:
    return {
        "artifactSegmentId": f"ESEG-{artifact_id}-{segment_index}",
        "artifactId": artifact_id,
        "artifactType": artifact_type,
        "documentVersionId": "DV-1",
        "sourceId": source_id,
        "segmentIndex": segment_index,
        "segmentCount": segment_count,
        "segmentKind": "complete",
        "payloadSlice": payload,
    }


def test_grounding_input_projects_only_the_persisted_shard_segments() -> None:
    from libs.review_evidence import grounding_input_for_evidence_shard

    shard = {
        "evidenceShardId": "ESHARD-1",
        "projectId": "P-1",
        "nodeId": 1,
        "artifactSegments": [
            _segment(
                artifact_id="EART-FIELD",
                artifact_type="field",
                source_id="FIELD-1",
                payload={"fieldKey": "licenseNo", "value": "TS1844171-2028", "pageNo": 1},
            ),
            _segment(
                artifact_id="EART-TABLE",
                artifact_type="table",
                source_id="TABLE-1",
                payload={"rows": [{"许可子项目": "工业管道(GC1)"}]},
                segment_index=1,
                segment_count=3,
            ),
            _segment(
                artifact_id="EART-SEAL",
                artifact_type="seal",
                source_id="SEAL-1",
                payload={"text": "广东省市场监督管理局", "pageNo": 1, "bbox": [1, 2, 3, 4]},
            ),
            _segment(
                artifact_id="EART-FRAGMENT",
                artifact_type="fragment",
                source_id="FRAGMENT-1",
                payload={"text": "GC1级覆盖GC2级", "pageNo": 1, "bbox": [5, 6, 7, 8]},
            ),
            _segment(
                artifact_id="EART-LINK",
                artifact_type="evidenceLink",
                source_id="EL-1",
                payload={
                    "id": "EL-1",
                    "documentVersionId": "DV-1",
                    "pageNo": 1,
                    "bbox": [5, 6, 7, 8],
                    "quotedText": "GC1级覆盖GC2级",
                },
            ),
        ],
    }

    projected = grounding_input_for_evidence_shard(shard)

    assert projected["evidenceShardId"] == "ESHARD-1"
    assert projected["documentVersionIds"] == ["DV-1"]
    assert projected["summary"] == {
        "fieldCount": 1,
        "tableCount": 1,
        "sealCount": 1,
        "fragmentCount": 1,
        "evidenceLinkCount": 1,
        "artifactSegmentCount": 5,
        "groundingStatus": "grounded",
    }
    assert projected["fields"][0]["artifactSegmentId"] == "ESEG-EART-FIELD-0"
    assert projected["tables"][0]["rows"] == [{"许可子项目": "工业管道(GC1)"}]
    assert projected["tables"][0]["segmentIndex"] == 1
    assert projected["seals"][0]["sourceId"] == "SEAL-1"
    assert projected["fragments"][0]["bbox"] == [5, 6, 7, 8]
    assert projected["evidenceLinks"][0]["id"] == "EL-1"
    assert "TS1844171-2028" in projected["evidenceTextCorpus"]
    assert "GC1级覆盖GC2级" in projected["evidenceTextCorpus"]
    assert "SIBLING-SHARD-CONTENT" not in str(projected)

