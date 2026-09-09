"""Prevent checklist generation from changing frozen condition-tool verdicts."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.business_pack import load_business_pack
from libs.integrations.errors import IntegrationServiceError
from libs.review_document_scope import validate_document_scope
from libs.review_rule_snapshot import effective_rule_snapshot
from libs.rule_condition_bindings import compile_condition_bindings

RESULT_VERDICTS = {"passed": "符合", "failed": "不符合", "evidence_insufficient": "证据不足", "not_applicable": "不适用"}


def condition_checklist_verdicts(run: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    rule = effective_rule_snapshot(run)
    if rule is None or rule.get("executionConditions") is None:
        return {}
    validate_document_scope(run)
    if not (run.get("documentScopeSnapshot") or {}).get("sourceFingerprint"):
        raise IntegrationServiceError("review", "checklist", reason="REVIEW_CONDITION_RESULT_MISSING")
    pack = deepcopy(load_business_pack(str(run.get("businessPackId") or "")))
    if run.get("atomicCheckToolBindingsSnapshot"):
        pack["atomicCheckToolBindings"] = deepcopy(run["atomicCheckToolBindingsSnapshot"])
    plan = compile_condition_bindings(rule, pack)
    rows = (context.get("atomicToolExecution") or {}).get("atomicResults") or []
    fixed = {}
    for replacement in plan["replacements"]:
        identity = replacement["atomicCheckId"]
        matches = [row for row in rows if row.get("atomicCheckId") == identity]
        outputs = matches[0].get("toolResults") or [] if len(matches) == 1 else []
        if len(outputs) != 1:
            raise IntegrationServiceError("review", "checklist", reason="REVIEW_CONDITION_RESULT_MISSING")
        output = outputs[0]
        result = output.get("result")
        if (output.get("toolName") != "evaluate_saved_conditions" or output.get("status") != "succeeded"
                or result not in RESULT_VERDICTS or matches[0].get("result") != result
                or output.get("conditionPlanHash") != plan["planHash"]
                or output.get("ruleSnapshotHash") != run["effectiveRuleSnapshot"]["snapshotHash"]
                or output.get("sourceSnapshotHash") != (run.get("documentScopeSnapshot") or {}).get("snapshotHash")):
            raise IntegrationServiceError("review", "checklist", reason="REVIEW_CONDITION_RESULT_MISMATCH")
        fixed[identity] = RESULT_VERDICTS[result]
    return fixed
