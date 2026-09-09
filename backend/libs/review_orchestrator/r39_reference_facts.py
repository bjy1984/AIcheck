"""Join one explicit instruction/procedure pair; never pick a first ambiguous row."""
from libs.review_tools.r39_reference import SCOPE_FIELDS


def _single_reference_input(state, run, groups, clean):
    names = ("referenceContexts", "referenceBases", "instructionReferences", "procedureIdentities")
    if any(len(groups[name]) != 1 for name in names):
        return None
    records = {name: clean(groups[name][0]) for name in names}
    scope = {key: records["referenceContexts"].get(key) for key in SCOPE_FIELDS}
    if scope["projectId"] != run["projectId"]:
        return None
    for prefix in ("instruction", "procedure"):
        document_id, version_id = scope[prefix + "DocumentId"], scope[prefix + "DocumentVersionId"]
        documents = [row for row in state.get("documents", []) if row.get("id") == document_id
                     and row.get("projectId") == run["projectId"] and row.get("tenantId") == run["tenantId"]]
        versions = [row for row in state.get("versions", []) if row.get("id") == version_id
                    and row.get("documentId") == document_id and row.get("tenantId") == run["tenantId"]]
        if len(documents) != 1 or len(versions) != 1 or version_id not in run.get("inputDocumentVersionIds", []):
            return None
    if any(any(record.get(key) != scope[key] for key in SCOPE_FIELDS) for record in records.values()):
        return None
    return {"projectId": run["projectId"], "scope": scope, "basis": records["referenceBases"],
            "instructionReference": records["instructionReferences"], "procedureIdentity": records["procedureIdentities"]}


def reference_input(state, run, groups, clean):
    """A declared inventory is never silently reduced to the first document pair."""
    from libs.review_tools.r39_tools import _text

    inventories = groups.get("referenceInventories", [])
    members = groups.get("referenceMembers", [])
    if not inventories and not members:
        return _single_reference_input(state, run, groups, clean)
    if len(inventories) != 1 or not members:
        return None
    inventory = clean(inventories[0])
    inventory["members"] = [clean(row) for row in members]
    keys = []
    for member in inventory["members"]:
        if any(not _text(member.get(field)) for field in SCOPE_FIELDS):
            return None
        key = tuple(member[field] for field in SCOPE_FIELDS)
        if key in keys:
            return None
        keys.append(key)
    names = ("referenceContexts", "referenceBases", "instructionReferences", "procedureIdentities")
    grouped = {key: {name: [] for name in names} for key in keys}
    for name in names:
        for row in groups[name]:
            if any(not _text(row.get(field)) for field in SCOPE_FIELDS):
                return None
            key = tuple(row[field] for field in SCOPE_FIELDS)
            if key not in grouped or grouped[key][name]:
                return None
            grouped[key][name].append(row)
    pairs = []
    for group in grouped.values():
        pair = _single_reference_input(state, run, group, clean)
        if pair is not None:
            pairs.append(pair)
    return {"projectId": run["projectId"], "inventory": inventory, "referencePairs": pairs}
