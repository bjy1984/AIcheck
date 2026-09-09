"""NB/T 47013.5-2015 6.3.2: one scoped emulsifier application requirement."""
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r39_content import SCOPE_FIELDS as DOCUMENT_SCOPE_FIELDS
from libs.review_tools.r39_tools import _refs, _text

SCOPE_FIELDS = (*DOCUMENT_SCOPE_FIELDS, "objectId", "eventId")


def evaluate_r39_pt_emulsifier_application(arguments):
    def finish(status, code, refs=()):
        output = result("evaluate_r39_pt_emulsifier_application", status,
                        facts={"scope": "selected_pt_emulsifier_application_only", "clause": "6.3.2",
                               "standard": "NB/T 47013.5-2015", "wholeRuleAcceptance": "not_evaluated",
                               "evidenceVerified": False},
                        checks=[check(code, status == "passed", status, "passed")],
                        rule_version="r39-pt-emulsifier-application-v1")
        output["evidenceRefs"] = deepcopy(list(refs))
        return output

    scope = arguments.get("scope")
    if (not isinstance(scope, dict) or any(not _text(scope.get(key)) for key in SCOPE_FIELDS)
            or scope["projectId"] != arguments.get("projectId")
            or scope["documentKind"] not in {"procedure", "instruction"} or scope["method"] != "PT"):
        return finish("evidence_insufficient", "r39_pt_scope_missing_or_unsupported")

    def matches(row):
        return isinstance(row, dict) and all(row.get(key) == scope[key] for key in SCOPE_FIELDS)

    basis, process = arguments.get("basis"), arguments.get("process")
    if (not matches(basis) or basis.get("standard") != "NB/T 47013.5-2015"
            or basis.get("clause") != "6.3.2" or basis.get("applicable") is not True or not _refs(basis)):
        return finish("evidence_insufficient", "r39_pt_basis_missing")
    refs = _refs(basis)
    if (not matches(process) or not _refs(process)
            or any(ref["documentVersionId"] != scope["documentVersionId"] for ref in _refs(process))):
        return finish("evidence_insufficient", "r39_pt_process_source_missing_or_conflicting", refs)
    refs.extend(_refs(process))
    removal = process.get("removalMethod")
    application = process.get("emulsifierApplication")
    if not _text(removal) or not _text(application):
        return finish("evidence_insufficient", "r39_pt_application_missing_or_unknown", refs)
    # Table 3 defines A water-washable, B lipophilic post-emulsifiable,
    # C solvent-removable and D hydrophilic post-emulsifiable. Do not infer A/C
    # from an absent emulsification record, nor ignore a conflicting supplied step.
    if removal in {"A", "C"}:
        if application != "none":
            return finish("evidence_insufficient", "r39_pt_non_emulsifying_process_conflict", refs)
        return finish("not_applicable", "r39_pt_no_emulsification_step", refs)
    if removal not in {"B", "D"} or application not in {"dip", "pour", "spray", "brush", "none"}:
        return finish("evidence_insufficient", "r39_pt_application_missing_or_unknown", refs)
    if application == "none":
        return finish("evidence_insufficient", "r39_pt_emulsification_step_not_described", refs)
    if application == "brush":
        return finish("failed", "r39_pt_emulsifier_brushing_prohibited", refs)
    if application == "spray" and removal == "B":
        return finish("failed", "r39_pt_spray_requires_hydrophilic_emulsifier", refs)
    return finish("passed", "r39_pt_emulsifier_application_permitted", refs)
