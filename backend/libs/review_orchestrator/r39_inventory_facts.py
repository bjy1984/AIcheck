"""Assemble inventory consistency inputs only from source-gated frozen facts."""
from copy import deepcopy


def build_inventory_consistency(run, groups, facts, clean):
    if facts["sourceValidation"]["inventoryConsistency"]["result"] != "passed":
        return
    sources = {"referenceInventory": "procedureReference", "documentInventory": "documentContent",
               "approvalInventory": "approvalChain", "applicationInventory": "firstUseValidation"}
    value = {"projectId": run["projectId"],
             "applicationDocumentLinks": [clean(row) for row in groups["applicationDocumentLinks"]],
             "unappliedInstructions": [{**clean(row), "documentVersionId": row.get("reviewedDocumentVersionId")}
                                        for row in groups["unappliedInstructions"]]}
    for key, name in sources.items():
        source = facts.get(name, {})
        if not isinstance(source.get("inventory"), dict):
            facts["sourceIssues"].append("r39_consistency_inventory_unavailable_" + name)
            return
        value[key] = deepcopy(source["inventory"])
    facts["inventoryConsistency"] = value
