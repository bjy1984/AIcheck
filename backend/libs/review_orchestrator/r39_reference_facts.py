"""Join one explicit instruction/procedure pair; never pick a first ambiguous row."""
from libs.review_tools.r39_reference import SCOPE_FIELDS


def reference_input(state, run, groups, clean):
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
