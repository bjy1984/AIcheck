"""審查插件：按工程選用、建立時凍結、沒選用就不載入也不外發；核心不直接依賴插件實作。"""
from __future__ import annotations

import ast
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from libs import review_plugins
from libs.business_pack import load_business_pack
from libs.review_orchestrator import execution as ex
from libs.review_plugins.settings import (
    freeze_review_plugins,
    project_plugin_enabled,
    run_plugin_enabled,
    validated_plugin_settings,
)

BACKEND = Path(__file__).resolve().parents[1]
ON = {"reviewPlugins": {"jev": {"enabled": True}}}
OFF = {"reviewPlugins": {"jev": {"enabled": False}}}


def test_project_setting_wins_over_the_legacy_allowlist(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "P")
    assert freeze_review_plugins({"id": "P", **OFF}) == {"jev": {"enabled": False, "source": "project_setting"}}
    assert freeze_review_plugins({"id": "P"}) == {"jev": {"enabled": True, "source": "legacy_allowlist"}}
    assert freeze_review_plugins({"id": "Q"}) == {"jev": {"enabled": False, "source": "default_off"}}
    assert freeze_review_plugins({"id": "Q", **ON}) == {"jev": {"enabled": True, "source": "project_setting"}}


def test_a_run_follows_its_frozen_snapshot_and_old_runs_follow_the_allowlist(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "P")
    assert run_plugin_enabled({"projectId": "P", "reviewPluginSnapshot": {"jev": {"enabled": False}}}, "jev") is False
    assert run_plugin_enabled({"projectId": "Q", "reviewPluginSnapshot": {"jev": {"enabled": True}}}, "jev") is True
    assert run_plugin_enabled({"projectId": "P"}, "jev") is True
    assert run_plugin_enabled({"projectId": "Q"}, "jev") is False


def test_upload_time_routing_uses_the_project_setting_then_its_own_allowlist(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_DOCUMENT_ROUTING_ALLOWED_PROJECTS", "P")
    legacy = "AICHECK_JEV_DOCUMENT_ROUTING_ALLOWED_PROJECTS"
    assert project_plugin_enabled({"id": "P"}, "jev", legacy_env=legacy) is True
    assert project_plugin_enabled({"id": "P", **OFF}, "jev", legacy_env=legacy) is False
    assert project_plugin_enabled({"id": "Q", **ON}, "jev", legacy_env=legacy) is True


@pytest.mark.parametrize("value", [None, [], {"other": {"enabled": True}}, {"jev": True},
                                   {"jev": {"enabled": "yes"}}, {"jev": {"enabled": True, "stages": ["x"]}}])
def test_only_known_plugins_with_a_boolean_switch_are_accepted(value):
    with pytest.raises(ValueError):
        validated_plugin_settings(value)


def test_an_unselected_plugin_step_is_skipped_without_loading_the_plugin():
    code = ("import sys\nfrom libs import review_plugins\n"
            "out = review_plugins.run_plugin_step('jev_decision', {}, "
            "{'projectId': 'P', 'reviewPluginSnapshot': {'jev': {'enabled': False}}}, {})\n"
            "print(out['status'], 'libs.review_plugins.jev' in sys.modules, "
            "any('jev' in name for name in sys.modules))")
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=True)
    assert result.stdout.split() == ["skipped", "False", "False"]


def test_hooks_contribute_nothing_when_the_run_did_not_select_a_plugin():
    run = {"projectId": "P", "reviewPluginSnapshot": {"jev": {"enabled": False}},
           "jevDecision": {"status": "completed", "atomic": [{"atomicCheckId": "AC-1", "choice": "failed"}],
                           "disagreementAtomicCheckIds": ["AC-1"]}}
    assert review_plugins.suggestion_fields(run) == {}
    assert review_plugins.prompt_requirements(run) == []
    assert review_plugins.prompt_payload(run) == {}


@pytest.fixture
def creation(monkeypatch):
    pack = load_business_pack("engineering_inspection_v1")
    state = {"review_runs": [], "ocr_parse_results": []}
    project = {"id": "P", "businessPackSnapshot": pack}
    repo = SimpleNamespace(state=state, clone=deepcopy, require_project=lambda _: project,
                           find_one=lambda *_a, **_k: None)
    monkeypatch.setattr(ex, "repo", repo)
    for name in ("ensure_review_state", "seed_graph_nodes", "append_review_event",
                 "bind_evidence_package_to_review_run", "freeze_review_run_clause_snapshot", "flush_state_records"):
        monkeypatch.setattr(ex, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(ex, "review_run_state_records", lambda _: {})
    monkeypatch.setattr(ex, "existing_scoped_run", lambda *args, **kwargs: None)
    monkeypatch.delenv("AICHECK_WORKSTATIONS_ENABLED", raising=False)
    monkeypatch.delenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", raising=False)

    def create(**setting):
        project.pop("reviewPlugins", None)
        project.update(setting)
        return ex.create_review_run_from_ai_run({"id": "AI-T", "projectId": "P", "nodeId": 16, "tenantId": "T",
                                                 "businessPackId": pack["id"], "inputDocumentVersionIds": ["V"]},
                                                mode="inline")
    return project, create


def test_plugin_choice_is_frozen_at_creation_and_only_a_selected_plugin_changes_the_input_hash(creation):
    project, create = creation
    default_run, off_run, on_run = create(), create(**OFF), create(**ON)
    assert default_run["reviewPluginSnapshot"] == {"jev": {"enabled": False, "source": "default_off"}}
    assert on_run["reviewPluginSnapshot"] == {"jev": {"enabled": True, "source": "project_setting"}}
    # 沒選用插件的審查，雜湊與改造前的公式一致，既有任務照常複用。
    assert default_run["inputHash"] == off_run["inputHash"] == ex.stable_hash_payload({
        "documentVersionIds": ["V"], "businessPackId": "engineering_inspection_v1",
        "clausePackageSnapshotHash": None, "promptVersion": None, "ruleSetVersion": None,
        "atomicCheckToolBindingSetHash": None})
    assert on_run["inputHash"] != default_run["inputHash"]
    # 之後改工程設定，不影響已建立的審查。
    project["reviewPlugins"] = {"jev": {"enabled": False}}
    assert run_plugin_enabled(on_run, "jev") is True
    replay = ex.clone_review_run_for_replay(on_run, run_mode="replay", reason="offline test")
    assert replay["reviewPluginSnapshot"] == on_run["reviewPluginSnapshot"]


# 只有插件自己、Jev 模組彼此、以及上傳時文件歸屬的背景任務（Celery 任務必須登記在 worker）
# 可以直接 import Jev 實作；其餘核心一律經 libs.review_plugins 登記表。
_ALLOWED_IMPORTERS = {
    "libs/review_plugins/__init__.py",  # 登記表本身：只在審查選用時延遲載入
    "libs/review_plugins/jev.py",
    "apps/worker/tasks.py",
    "libs/integrations/task_dispatcher.py",
}


def _jev_module(name: str) -> bool:
    last = name.rsplit(".", 1)[-1]
    return last.startswith("jev_") or name == "libs.review_plugins.jev"


def test_core_code_never_imports_jev_directly():
    offenders = []
    for path in sorted([*BACKEND.glob("libs/**/*.py"), *BACKEND.glob("apps/**/*.py")]):
        relative = path.relative_to(BACKEND).as_posix()
        if relative in _ALLOWED_IMPORTERS or path.name.startswith("jev_"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] + [f"{node.module}.{alias.name}" for alias in node.names]
                     if isinstance(node, ast.ImportFrom) else [])
            if any(_jev_module(name) for name in names):
                offenders.append(relative)
    assert offenders == []


def _client():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    return TestClient(app)


def test_only_an_admin_can_switch_a_projects_plugin_and_it_is_validated():
    from libs.db.repository import repo

    client = _client()
    project_id = "P-2026-HDCP-001"
    before = deepcopy(repo.require_project(project_id).get("reviewPlugins"))
    try:
        denied = client.put(f"/projects/{project_id}/review-plugins", json={"reviewPlugins": {"jev": {"enabled": True}}},
                            headers={"X-Role": "inspection"})
        assert denied.json()["code"] == 403, denied.text
        invalid = client.put(f"/projects/{project_id}/review-plugins", json={"reviewPlugins": {"jev": {"enabled": "on"}}},
                             headers={"X-Role": "admin"})
        assert invalid.json()["data"]["reason"] == "VALIDATION_ERROR", invalid.text
        saved = client.put(f"/projects/{project_id}/review-plugins", json={"reviewPlugins": {"jev": {"enabled": True}}},
                           headers={"X-Role": "admin"})
        assert saved.json()["code"] == 0, saved.text
        assert saved.json()["data"]["project"]["reviewPlugins"] == {"jev": {"enabled": True}}
    finally:
        project = repo.require_project(project_id)
        if before is None:
            project.pop("reviewPlugins", None)
        else:
            project["reviewPlugins"] = before


def test_plugin_catalog_says_only_whether_the_deployment_can_run_it(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_API_KEY", "secret-test-value")
    monkeypatch.setenv("AICHECK_JEV_ENABLED", "true")
    monkeypatch.delenv("AICHECK_JEV_DATA_EGRESS_APPROVED", raising=False)
    response = _client().get("/review-plugins")
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [(item["id"], item["deploymentAvailable"]) for item in items] == [("jev", False)]
    assert "secret-test-value" not in response.text
