import json
from copy import deepcopy

import pytest

from libs.review_document_scope import freeze_document_scope
from libs.review_grounding import build_grounded_review_input, grounding_prompt_block


def scoped_sources():
    run = {"projectId": "P", "nodeId": 16, "inputDocumentVersionIds": ["V"],
           "inputDocumentPageRanges": {"V": {"start": 2, "end": 2}}}
    state = {"ocr_parse_results": [{"documentVersionId": "V", "fullText": "OUTSIDE_FULLTEXT",
                                   "fragments": [{"pageNo": 1, "text": "OUTSIDE_FRAGMENT"},
                                                 {"pageNo": 2, "text": "SELECTED_FRAGMENT"}],
                                   "tables": [{"pageNo": 2, "contentMarkdown": "SELECTED_TABLE"},
                                              {"pageNo": 3, "contentMarkdown": "OUTSIDE_TABLE"}]}],
             "extracted_fields": [{"documentVersionId": "V", "pageNo": page,
                                   "fieldName": "grade", "fieldValue": text}
                                  for page, text in [(1, "OUTSIDE_FIELD"), (2, "SELECTED_FIELD"),
                                                     (None, "OUTSIDE_UNKNOWN")]],
             "evidence_links": [{"id": text, "documentVersionId": "V", "pageNo": page,
                                 "quotedText": text}
                                for page, text in [(2, "SELECTED_LINK"), (3, "OUTSIDE_LINK")]]}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    return run, state


def test_grounding_and_prompt_exclude_outside_evidence_from_all_source_stores():
    run, state = scoped_sources()
    original = deepcopy(state)
    result = build_grounded_review_input(state, ["V"], review_run=run)
    text = json.dumps(grounding_prompt_block(result))
    assert "OUTSIDE" not in text
    for marker in ("SELECTED_FRAGMENT", "SELECTED_TABLE", "SELECTED_FIELD", "SELECTED_LINK"):
        assert marker in text
    assert state == original


@pytest.mark.parametrize("key", ["extracted_fields", "evidence_links"])
def test_independent_evidence_store_changes_invalidate_frozen_inputs(key):
    run, state = scoped_sources()
    state[key][0]["quotedText"] = "CHANGED"
    with pytest.raises(ValueError, match="sources_changed"):
        build_grounded_review_input(state, ["V"], review_run=run)


def test_grounding_scope_cannot_expand_and_empty_subset_stays_empty():
    run, state = scoped_sources()
    with pytest.raises(ValueError, match="scope_expansion"):
        build_grounded_review_input(state, ["FOREIGN"], review_run=run)
    result = build_grounded_review_input(state, [], review_run=run)
    assert not result["fields"] and not result["tables"] and not result["evidenceLinks"]
    assert result["groundingStatus"] == "insufficient_evidence"


def test_without_range_legacy_grounding_is_unchanged():
    run, state = scoped_sources()
    del run["inputDocumentPageRanges"]
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    assert build_grounded_review_input(state, ["V"], review_run=run) == build_grounded_review_input(state, ["V"])


def test_prompt_builder_replaces_unscoped_cached_grounding(monkeypatch):
    from types import SimpleNamespace

    from libs.business_pack import load_business_pack
    from libs.review_orchestrator import execution as ex

    run, state = scoped_sources()
    pack = load_business_pack("engineering_inspection_v1")
    monkeypatch.setattr(ex, "repo", SimpleNamespace(state=state, clone=deepcopy))
    monkeypatch.setattr(ex, "select_prompt_template", lambda _: None)
    monkeypatch.setattr(ex, "build_ai_review_prompt", lambda *args, **kwargs: {
        "system": "Review", "user": "{{reviewTaskJson}}", "template": {}})
    monkeypatch.setattr(ex, "audit_runtime_public_config", lambda **kwargs: {})
    monkeypatch.setattr(ex.checklist_mode, "checklist_enabled", lambda: False)
    context = {"project": {"businessPackSnapshot": pack}, "auditRuntime": {"mode": "structured"},
               "groundingInput": {"fragments": [{"text": "OUTSIDE_CACHED"}]},
               "fields": [{"fieldValue": "OUTSIDE_CACHED_FIELD"}],
               "evidenceLinks": [{"id": "OUTSIDE_CACHED_LINK"}]}
    result = ex.build_review_prompt_parts(run, context)
    assert "OUTSIDE" not in json.dumps(result["messages"])
    assert result["userPayload"]["documentPageRanges"] == {"V": {"start": 2, "end": 2}}
    assert result["userPayload"]["evidenceLinkIds"] == ["SELECTED_LINK"]
