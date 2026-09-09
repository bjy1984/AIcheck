"""Aggregate selected OCR file pairs without inventing a complete project inventory."""
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import result
from libs.review_tools.r39_tools import _text


def evaluate_field_pairs(arguments, evaluate_one):
    selected, pairs = arguments.get("selectedDocumentVersionIds"), arguments.get("fieldPairs")
    issues = deepcopy(arguments.get("selectionIssues", []))
    outputs, used = [], set()
    selected_valid = isinstance(selected, list) and bool(selected) and all(_text(item) for item in selected) and len(set(selected)) == len(selected)
    if (not selected_valid or not isinstance(pairs, list) or not pairs or not isinstance(issues, list)
            or any(not isinstance(item, dict) or not _text(item.get("code")) for item in issues)):
        issues = [{"code": "r39_ocr_pair_collection_invalid"}]
        pairs = []
    grouped = {}
    for pair in pairs:
        if (not isinstance(pair, dict) or any(key in pair for key in ("fieldPairs", "inventory", "referencePairs"))
                or pair.get("identityMode") != "exact_source_organization_name" or pair.get("projectId") != arguments.get("projectId")):
            issues.append({"code": "r39_ocr_pair_invalid"})
            continue
        scope = pair.get("scope")
        if (not isinstance(scope, dict) or any(scope.get(prefix + "DocumentVersionId") not in selected for prefix in ("instruction", "procedure"))):
            issues.append({"code": "r39_ocr_pair_outside_selection"})
            continue
        grouped.setdefault(scope["instructionDocumentVersionId"], []).append(pair)
    for version, candidates in sorted(grouped.items()):
        if len(candidates) != 1:
            issues.append({"code": "r39_ocr_instruction_pair_duplicate", "documentVersionId": version})
            continue
        pair = candidates[0]
        output = evaluate_one(pair)
        output["pairScope"] = deepcopy(pair["scope"])
        outputs.append(output)
        used.update(pair["scope"][prefix + "DocumentVersionId"] for prefix in ("instruction", "procedure"))
    statuses = {item["result"] for item in outputs}
    covered = selected_valid and set(selected) == used and not issues
    status = "failed" if "failed" in statuses else "passed" if covered and statuses == {"passed"} else "evidence_insufficient"
    output = result("evaluate_r39_procedure_reference", status,
        facts={"scope": "selected_ocr_document_pairs_only", "pairResults": outputs, "selectionIssues": issues,
               "coverage": {"selectedDocumentCount": len(selected) if selected_valid else None, "comparedPairCount": len(outputs),
                            "unresolvedDocumentVersionIds": sorted(set(selected) - used) if selected_valid else [],
                            "complete": bool(covered and statuses <= {"passed", "failed"})},
               "organizationIdentityVerified": False, "wholeRuleAcceptance": "not_evaluated", "evidenceVerified": False},
        checks=[], rule_version="r39-selected-ocr-pairs-v1")
    output["evidenceRefs"] = [deepcopy(ref) for item in outputs for ref in item.get("evidenceRefs", [])]
    return output
