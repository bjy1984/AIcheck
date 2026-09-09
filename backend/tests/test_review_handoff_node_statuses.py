from copy import deepcopy

import pytest
from test_review_handoff_api import (  # noqa: F401 - shared autouse API fixture
    HEADERS,
    PROJECT,
    client,
    setup,
)

from libs.db.repository import repo

URL = f"/api/projects/{PROJECT}/review-handoff-node-statuses"


def test_nodes_without_selected_handoff_report_not_used():
    result = client.get(URL, headers=HEADERS).json()
    assert result["code"] == 0, result
    assert len(result["data"]["items"]) == 69
    assert result["data"]["requiresRevalidationCount"] == 0
    assert result["data"]["automaticRerun"] is False
    assert all(item["status"] == "not_used" for item in result["data"]["items"])


def test_invalid_handoff_snapshot_is_counted_once_and_history_is_preserved():
    target = repo.find_one("review_runs", "TARGET")
    target["handoffInputsSnapshot"] = {"items": []}  # Broken persisted dependency must require revalidation.
    before = deepcopy(repo.state["review_runs"])
    result = client.get(URL, headers=HEADERS).json()["data"]
    assert result["requiresRevalidationCount"] == 1
    assert next(row for row in result["items"] if row["nodeId"] == 35)["reviewRunId"] == "TARGET"
    assert repo.state["review_runs"] == before
    assert result["historicalResultsPreserved"] is True


def test_active_session_determines_which_run_counts():
    target = repo.find_one("review_runs", "TARGET")
    target["handoffInputsSnapshot"] = {"items": []}
    current = deepcopy(target)
    current.update(id="CURRENT", reviewRunId="CURRENT")
    current.pop("handoffInputsSnapshot")
    repo.state["review_runs"].append(current)
    repo.state.setdefault("review_sessions", []).append({"id": "SESSION", "projectId": PROJECT, "nodeId": 35,
        "tenantId": "TENANT-DEFAULT", "createdBy": HEADERS["X-User-Id"], "status": "active", "activeReviewRunId": "CURRENT"})
    result = client.get(URL, headers=HEADERS).json()["data"]
    row = next(row for row in result["items"] if row["nodeId"] == 35)
    assert row["reviewRunId"] == "CURRENT"
    assert result["requiresRevalidationCount"] == 0


def test_inaccessible_source_is_unknown_not_zero_and_does_not_expose_run():
    repo.find_one("review_runs", "TARGET")["inputDocumentVersionIds"] = ["SECRET-VERSION"]
    result = client.get(URL, headers=HEADERS).json()["data"]
    row = next(row for row in result["items"] if row["nodeId"] == 35)
    assert row == {"nodeId": 35, "status": "unavailable", "requiresRevalidation": None}
    assert result["unavailableCount"] == 1
    assert "SECRET" not in str(result)


def test_node_scope_limits_the_summary_before_dependency_checks(monkeypatch):
    from apps.api import routes

    repo.find_one("review_runs", "TARGET")["handoffInputsSnapshot"] = {"items": []}
    monkeypatch.setattr(routes, "authorized_node_scope", lambda request, project: {24})
    result = client.get(URL, headers=HEADERS).json()["data"]
    assert [item["nodeId"] for item in result["items"]] == [24]
    assert result["requiresRevalidationCount"] == 0
    assert "TARGET" not in str(result)


@pytest.mark.parametrize("case", ["role", "disabled"])
def test_status_list_preserves_role_and_feature_guard(case, monkeypatch):
    headers = dict(HEADERS)
    if case == "role": headers["X-Role"] = "contractor"
    else: monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "false")
    assert client.get(URL, headers=headers).json()["code"] != 0
