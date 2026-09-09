"""Authorize handoff inputs before creating an AI task or dispatching work."""
from __future__ import annotations

from libs.business_pack import matching_rule_for_node
from libs.review_document_scope import freeze_document_scope
from libs.review_handoff_inputs import freeze_handoff_inputs
from libs.review_rule_snapshot import freeze_effective_rule
from libs.review_workstations import freeze_station


def prepare_handoff_selection(services, request, project_id, node_id, body, versions, ranges):
    from apps.api import review_handoff_routes as routes
    from libs.review_orchestrator.runtime_tools import runtime_tool_catalog

    selection = body["handoffSelection"]
    if not isinstance(selection, dict) or not isinstance(selection.get("items"), list):
        raise TypeError("请选择已核验的交接及其对应对象。")
    services.repo.ensure_deferred_loaded("review_handoffs", "review_runs", "ocr_parse_results", "fact_corrections")
    visible = routes._visible_versions(request, project_id)
    for item in selection["items"]:
        if not isinstance(item, dict):
            raise TypeError("交接选择无效。")
        record = services.repo.find_one("review_handoffs", item.get("handoffId"))
        if not record or record.get("projectId") != project_id or services.tenant_id_for_record(record) != services.request_tenant_id(request):
            raise ValueError("交接不存在或当前账号无法访问。")
        _, error = routes._record_view(request, project_id, record, visible)
        if error is not None:
            raise ValueError("当前账号无法访问交接所依赖的节点或文件版本。")
    project = services.repo.require_project(project_id)
    pack = services.business_pack_for_project(project)
    rule = services.current_published_rule_for_node(node_id, business_pack_id=pack["id"], project_id=project_id) or matching_rule_for_node(pack, node_id)
    run = {"projectId": project_id, "tenantId": services.request_tenant_id(request), "nodeId": node_id,
           "businessPackId": pack["id"], "inputDocumentVersionIds": versions}
    if "inputDocumentPageRanges" in body:
        run["inputDocumentPageRanges"] = ranges
    if "conditionObjectMapping" in body:
        run["conditionObjectMapping"] = services.repo.clone(body["conditionObjectMapping"])
    run["documentScopeSnapshot"] = freeze_document_scope(run, services.repo.state)
    run["effectiveRuleSnapshot"] = freeze_effective_rule(run, rule)
    run["workstationSnapshot"] = freeze_station(node_id, pack, runtime_tool_catalog())
    freeze_handoff_inputs(run, services.repo.state, selection)
    return services.repo.clone(selection)
