"""Validate explicit object choices against authorized new-task inputs."""
from __future__ import annotations

from libs.review_condition_mapping import freeze_condition_mapping
from libs.review_document_scope import freeze_document_scope
from libs.review_rule_snapshot import freeze_effective_rule
from libs.rule_condition_bindings import compile_condition_bindings


def prepare_condition_selection(services, request, project_id, node_id, body, versions, ranges):
    project = services.repo.require_project(project_id)
    pack = services.business_pack_for_project(project)
    rule = services.current_published_rule_for_node(node_id, business_pack_id=pack["id"], project_id=project_id)
    if not rule or not rule.get("executionConditions"):
        raise ValueError("当前生效规则没有可执行条件，请在规则发布并试跑后重新选择对象。")
    compile_condition_bindings(rule, pack)
    services.repo.ensure_deferred_loaded("ocr_parse_results", "fact_corrections")
    run = {"projectId": project_id, "nodeId": node_id, "tenantId": services.request_tenant_id(request),
           "businessPackId": pack["id"], "inputDocumentVersionIds": versions}
    if "inputDocumentPageRanges" in body:
        run["inputDocumentPageRanges"] = ranges
    run["documentScopeSnapshot"] = freeze_document_scope(run, services.repo.state)
    run["effectiveRuleSnapshot"] = freeze_effective_rule(run, rule)
    freeze_condition_mapping(run, services.repo.state, body["conditionObjectMapping"])
    return services.repo.clone(body["conditionObjectMapping"])
