from libs.db.repository import STATE_COLLECTIONS, repo
from libs.standard_knowledge_canonical import select_canonical_field


def test_new_mineru_value_wins_and_old_only_value_survives():
    selected = select_canonical_field(
        "publicationDate",
        [
            {"value": "2014-01-01", "sourceType": "legacy_ocr", "sourceId": "OLD"},
            {"value": "2015-04-02", "sourceType": "new_mineru", "sourceId": "NEW"},
        ],
    )
    assert selected["value"] == "2015-04-02"
    assert selected["authority"] == "current"
    assert selected["selectedSourceId"] == "NEW"
    assert {item["sourceId"] for item in selected["sources"]} == {"OLD", "NEW"}

    legacy_only = select_canonical_field(
        "filingNumber",
        [{"value": "61188-2018", "sourceType": "legacy_ocr", "sourceId": "OLD"}],
    )
    assert legacy_only["value"] == "61188-2018"
    assert legacy_only["authority"] == "legacy_only"


def test_canonical_collection_is_persisted_state():
    assert STATE_COLLECTIONS["standard_knowledge_records"] == "standard_knowledge_records"
    assert "standard_knowledge_records" in repo.state
