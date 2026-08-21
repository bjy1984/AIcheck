from __future__ import annotations

from libs.knowledge_indexing import build_chunks_for_file, build_vector_rows, offline_hash_embeddings


def test_chunks_and_vectors_capture_final_classification_metadata() -> None:
    knowledge_file = {
        "id": "KF-UNCLASSIFIED-1",
        "fileName": "扫描件001.pdf",
        "documentId": "DOC-UNCLASSIFIED-1",
        "documentVersionId": "DV-UNCLASSIFIED-1",
        "sourceId": "KS-PROJECT-FILE",
        "projectId": "P-001",
        "materialCategory": "未分类资料",
        "materialTypeCode": "unclassified_material",
        "materialTypeName": "未分类资料",
        "classificationStatus": "unclassified",
        "classificationConfidence": 0.0,
        "contextType": "project_material",
    }
    chunks = build_chunks_for_file(
        knowledge_file,
        [
            {
                "pageNo": 1,
                "text": "无法分类但可检索的工程事实，设计压力为2.5MPa。",
                "bbox": [10, 20, 500, 80],
            }
        ],
    )

    assert chunks[0]["projectId"] == "P-001"
    assert chunks[0]["materialTypeCode"] == "unclassified_material"
    assert chunks[0]["materialTypeName"] == "未分类资料"
    assert chunks[0]["classificationStatus"] == "unclassified"
    assert chunks[0]["classificationConfidence"] == 0.0

    embeddings = offline_hash_embeddings([chunk["text"] for chunk in chunks])
    vectors = build_vector_rows(
        knowledge_file,
        chunks,
        embeddings,
        embedding_model="offline-hash-test",
    )
    assert vectors[0]["payload"]["materialTypeCode"] == "unclassified_material"
    assert vectors[0]["payload"]["classificationStatus"] == "unclassified"
    assert vectors[0]["payload"]["projectId"] == "P-001"
