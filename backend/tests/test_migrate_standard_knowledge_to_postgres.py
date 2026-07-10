from scripts.migrate_standard_knowledge_to_postgres import STANDARD_SOURCE_ID, select_standard_rows


def test_select_standard_rows_excludes_project_knowledge_and_keeps_dependencies():
    grouped = {
        "knowledge_sources": [
            (STANDARD_SOURCE_ID, {"id": STANDARD_SOURCE_ID}),
            ("KS-PROJECT-FILE", {"id": "KS-PROJECT-FILE"}),
        ],
        "knowledge_files": [
            (
                "KF-STD",
                {
                    "id": "KF-STD",
                    "sourceId": STANDARD_SOURCE_ID,
                    "documentId": "KDOC-STD",
                    "documentVersionId": "KDV-STD",
                },
            ),
            ("KF-PROJECT", {"id": "KF-PROJECT", "sourceId": "KS-PROJECT-FILE"}),
        ],
        "knowledge_chunks": [
            ("CHK-STD", {"id": "CHK-STD", "fileId": "KF-STD", "sourceId": STANDARD_SOURCE_ID}),
            ("CHK-PROJECT", {"id": "CHK-PROJECT", "fileId": "KF-PROJECT"}),
        ],
        "knowledge_vectors": [
            ("KV-STD", {"id": "KV-STD", "chunkId": "CHK-STD"}),
            ("KV-PROJECT", {"id": "KV-PROJECT", "chunkId": "CHK-PROJECT"}),
        ],
        "documents": [
            ("KDOC-STD", {"id": "KDOC-STD"}),
            ("DOC-PROJECT", {"id": "DOC-PROJECT"}),
        ],
        "document_versions": [
            ("KDV-STD", {"id": "KDV-STD", "documentId": "KDOC-STD"}),
        ],
        "ocr_parse_results": [
            ("PARSE-STD", {"id": "PARSE-STD", "documentVersionId": "KDV-STD"}),
        ],
    }

    selected = select_standard_rows(grouped)

    assert [row[0] for row in selected["knowledge_files"]] == ["KF-STD"]
    assert [row[0] for row in selected["knowledge_chunks"]] == ["CHK-STD"]
    assert [row[0] for row in selected["knowledge_vectors"]] == ["KV-STD"]
    assert [row[0] for row in selected["documents"]] == ["KDOC-STD"]
    assert [row[0] for row in selected["document_versions"]] == ["KDV-STD"]
    assert [row[0] for row in selected["ocr_parse_results"]] == ["PARSE-STD"]
