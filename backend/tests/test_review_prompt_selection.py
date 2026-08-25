from __future__ import annotations

from libs.db.repository import repo
from libs.review_orchestrator.execution import select_prompt_template


def prompt_template(template_id: str, prompt_key: str) -> dict:
    return {
        "id": template_id,
        "name": template_id,
        "promptKey": prompt_key,
        "version": "2026.08",
        "promptVersionId": f"PROMPT-{template_id}",
        "status": "production",
        "businessPackId": "engineering_inspection_v1",
        "systemPrompt": "system",
        "userPromptTemplate": "{{reviewTaskJson}}",
    }


def test_review_run_never_selects_classifier_prompt_even_when_version_matches(monkeypatch) -> None:
    classifier = prompt_template("PTPL-CLASSIFIER", "document-material-classifier")
    review = prompt_template("PTPL-REVIEW", "review_prompt")
    monkeypatch.setitem(repo.state, "prompt_templates", [classifier, review])

    selected = select_prompt_template(
        {
            "promptVersion": classifier["promptVersionId"],
            "businessPackId": "engineering_inspection_v1",
        }
    )

    assert selected is not None
    assert selected["id"] == "PTPL-REVIEW"
    assert selected["promptKey"] == "review_prompt"


def test_review_run_has_no_prompt_fallback_when_only_classifier_template_exists(monkeypatch) -> None:
    classifier = prompt_template("PTPL-CLASSIFIER", "document-material-classifier")
    monkeypatch.setitem(repo.state, "prompt_templates", [classifier])

    selected = select_prompt_template(
        {"promptVersion": "node-1-v1", "businessPackId": "engineering_inspection_v1"}
    )

    assert selected is None
