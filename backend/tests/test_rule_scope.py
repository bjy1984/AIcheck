from __future__ import annotations

from copy import deepcopy

import pytest

from apps.api.routes import matching_rule_target
from libs.business_pack.loader import DEFAULT_BUSINESS_PACK_ID
from libs.db.repository import repo
from libs.review_orchestrator.execution import current_published_rule_for_node
from libs.rule_scope import same_rule_scope


@pytest.fixture
def scoped_rules(monkeypatch):
    base = {"ruleKey": "R24", "nodeIds": [24], "status": "已发布"}
    rows = [
        {**base, "id": "GLOBAL", "publishedAt": "2026-09-08"},
        {**base, "id": "P1", "projectId": "P1", "publishedAt": "2026-09-01"},
        {**base, "id": "P2", "projectId": "P2", "publishedAt": "2026-09-09"},
        {**base, "id": "OTHER-PACK", "businessPackId": "other", "publishedAt": "2026-09-10"},
    ]
    monkeypatch.setitem(repo.state, "rule_versions", rows)
    return rows


@pytest.mark.parametrize("project,expected", [(None, "GLOBAL"), ("P1", "P1"), ("P2", "P2"), ("P3", "GLOBAL")])
def test_project_override_precedes_newer_global_rule(scoped_rules, project, expected):
    result = current_published_rule_for_node(24, project_id=project, business_pack_id=DEFAULT_BUSINESS_PACK_ID)
    assert result["id"] == expected
    result["status"] = "changed"
    assert all(row["status"] == "已发布" for row in scoped_rules)


def test_retired_override_falls_back_without_leaking_other_project(scoped_rules):
    scoped_rules[1]["status"] = "已回滚"
    assert current_published_rule_for_node(24, project_id="P1", business_pack_id=DEFAULT_BUSINESS_PACK_ID)["id"] == "GLOBAL"
    assert current_published_rule_for_node(25, project_id="P1") is None
    assert current_published_rule_for_node(24)["id"] == "GLOBAL"


@pytest.mark.parametrize("target", ["GLOBAL", "P2", "OTHER-PACK"])
def test_rollback_cannot_cross_project_or_pack(scoped_rules, target):
    assert matching_rule_target(scoped_rules[1], target_version_id=target) is None


def test_version_name_lookup_filters_scope_before_selecting(scoped_rules):
    for row in scoped_rules:
        row["version"] = "v1"
    prior = deepcopy(scoped_rules[1])
    prior.update(id="P1-OLD", version="v0")
    scoped_rules.insert(0, {**scoped_rules[2], "version": "v0"})
    scoped_rules.append(prior)
    assert matching_rule_target(scoped_rules[1], target_version_id="OTHER-PACK") is None
    assert matching_rule_target(prior, target_version="v1")["id"] == "P1"
    assert same_rule_scope({}, {"businessPackId": DEFAULT_BUSINESS_PACK_ID})
    assert not same_rule_scope(prior, scoped_rules[0])


def test_窄节点规则胜过一口气声明四个节点的老种子(monkeypatch):
    """并列发布时间下，只声明本节点的规则必须稳定胜出。

    2026-09-11 生产：老种子 RULE-WELDER-202606（焊工资格核验）声明
    nodeIds [24, 25, 27, 28]，publishedAt 与业务包 R25/R27 完全相同，
    选谁只由列表顺序决定。两种顺序都要选中节点自己的规则。
    """
    specific = {"id": "RULE-ENG-INSP-R25", "nodeIds": [25], "status": "已发布", "publishedAt": "2026-06-26 09:12:00"}
    bundle = {"id": "RULE-WELDER-202606", "nodeIds": [24, 25, 27, 28], "status": "已发布", "publishedAt": "2026-06-26 09:12:00"}
    for rows in ([specific, bundle], [bundle, specific]):
        monkeypatch.setitem(repo.state, "rule_versions", deepcopy(rows))
        assert current_published_rule_for_node(25)["id"] == "RULE-ENG-INSP-R25"
        assert current_published_rule_for_node(24)["id"] == "RULE-WELDER-202606"


def test_发布时间新的仍然优先于覆盖窄的(monkeypatch):
    """窄优先只是并列时的决胜项，不能盖过「新发布的规则生效」。"""
    old_specific = {"id": "OLD-R25", "nodeIds": [25], "status": "已发布", "publishedAt": "2026-06-26 09:12:00"}
    new_bundle = {"id": "NEW-BUNDLE", "nodeIds": [24, 25], "status": "已发布", "publishedAt": "2026-09-11 10:00:00"}
    monkeypatch.setitem(repo.state, "rule_versions", [old_specific, new_bundle])
    assert current_published_rule_for_node(25)["id"] == "NEW-BUNDLE"
