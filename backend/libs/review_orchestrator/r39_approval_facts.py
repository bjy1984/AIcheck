"""Join declared approval cycles while preserving source and reviewed revisions."""
from libs.review_tools.r39_approval import SCOPE_FIELDS
from libs.review_tools.r39_tools import _text


def build_approval_inputs(state, run, groups, facts, clean, document_valid):
    inventories, members = groups["approvalCycleInventories"], groups["approvalCycleMembers"]
    if not inventories and not members:
        _single_input(state, run, groups, facts, clean, document_valid)
        return
    if len(inventories) != 1 or not members:
        facts["sourceIssues"].append("r39_approval_cycle_inventory_missing_or_ambiguous")
        return
    inventory = clean(inventories[0])
    inventory["members"] = [clean(row) for row in members]
    names = ("approvalContexts", "requirements", "steps", "signatureInventories", "signatures")
    grouped = {}
    for member in inventory["members"]:
        if any(not _text(member.get(key)) for key in SCOPE_FIELDS):
            facts["sourceIssues"].append("r39_approval_cycle_inventory_member_invalid")
            return
        key = tuple(member[field] for field in SCOPE_FIELDS)
        if key in grouped:
            facts["sourceIssues"].append("r39_approval_cycle_inventory_member_duplicate")
            return
        grouped[key] = {name: [] for name in names}
    invalid = False
    for name in names:
        for row in groups[name]:
            record = clean(row)
            if any(not _text(record.get(field)) for field in SCOPE_FIELDS):
                invalid = True
                continue
            key = tuple(record[field] for field in SCOPE_FIELDS)
            if key not in grouped:
                invalid = True
                continue
            grouped[key][name].append(row)
    approvalCycles = [{}] if invalid else []
    for group in grouped.values():
        individual = {"sourceIssues": []}
        _single_input(state, run, group, individual, clean, document_valid)
        facts["sourceIssues"].extend(individual["sourceIssues"])
        if "approvalChain" in individual:
            approvalCycles.append(individual["approvalChain"])
    facts["approvalChain"] = {"projectId": run["projectId"], "inventory": inventory, "approvalCycles": approvalCycles}


def _single_input(state, run, groups, facts, clean, document_valid):
    issues = facts["sourceIssues"]
    contexts = groups["approvalContexts"]
    if len(contexts) != 1:
        issues.append("r39_approval_context_missing_or_ambiguous")
        return
    context = clean(contexts[0])
    scope = {key: context.get(key) for key in SCOPE_FIELDS}
    if not document_valid(state, run, scope):
        issues.append("r39_reviewed_document_not_in_selected_project_scope")
        return
    source_documents = {row["id"]: row.get("documentId") for row in state.get("versions", [])
                        if row.get("tenantId") == run["tenantId"]}
    for name in ("signatureInventories", "signatures"):
        for row in groups[name]:
            source_version = row.get("documentVersionId")
            # Separate approval registers may cite this revision. A signature
            # taken from another revision of the reviewed file itself cannot.
            if source_documents.get(source_version) == scope["documentId"] and source_version != scope["documentVersionId"]:
                issues.append("r39_approval_signature_from_other_document_revision")
                return
    records = {key: [clean(row) for row in groups[key]]
               for key in ("requirements", "steps", "signatureInventories", "signatures")}
    if any(len(records[key]) != 1 for key in ("requirements", "signatureInventories")):
        issues.append("r39_approval_header_missing_or_ambiguous")
        return
    if any(any(row.get(key) != scope[key] for key in SCOPE_FIELDS) for rows in records.values() for row in rows):
        issues.append("r39_approval_source_scope_conflict")
        return
    requirements = records["requirements"][0]
    inventory = records["signatureInventories"][0]
    # Embedded child records cannot manufacture evidence; independent rows are required.
    requirements["steps"] = [{key: value for key, value in row.items() if key not in SCOPE_FIELDS}
                             for row in records["steps"]]
    inventory["signatures"] = records["signatures"]
    facts["approvalChain"] = {"projectId": run["projectId"], "scope": scope,
                              "requirements": requirements, "signatureInventory": inventory}
    return
