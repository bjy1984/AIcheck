"""Frozen document/object/event adapter for the PT application requirement."""
from libs.review_tools.r39_pt import SCOPE_FIELDS


def pt_application_input(state, run, groups, clean, document_valid):
    names = ("ptContexts", "ptBases", "ptProcesses")
    if any(len(groups[name]) != 1 for name in names):
        return None
    records = {name: clean(groups[name][0]) for name in names}
    scope = {key: records["ptContexts"].get(key) for key in SCOPE_FIELDS}
    if not document_valid(state, run, scope):
        return None
    if any(any(row.get(key) != scope[key] for key in SCOPE_FIELDS) for row in records.values()):
        return None
    return {"projectId": run["projectId"], "scope": scope, "basis": records["ptBases"], "process": records["ptProcesses"]}
