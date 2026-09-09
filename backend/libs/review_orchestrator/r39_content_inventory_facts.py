"""Join all declared document versions; source locations remain attached to rows."""
from libs.review_tools.r39_content import SCOPE_FIELDS
from libs.review_tools.r39_tools import _text


def build_content_inputs(state, run, groups, facts, clean, build_one):
    inventories, members = groups["contentDocumentInventories"], groups["contentDocumentMembers"]
    if not inventories and not members:
        build_one(state, run, groups, facts)
        return
    if len(inventories) != 1 or not members:
        facts["sourceIssues"].append("r39_document_inventory_missing_or_ambiguous")
        return
    inventory = clean(inventories[0])
    inventory["members"] = [clean(row) for row in members]
    names = ("contentContexts", "contentBases", "contentInventories", "contentFields")
    grouped = {}
    for member in inventory["members"]:
        if any(not _text(member.get(key)) for key in SCOPE_FIELDS):
            facts["sourceIssues"].append("r39_document_inventory_member_invalid")
            return
        key = tuple(member[field] for field in SCOPE_FIELDS)
        if key in grouped:
            facts["sourceIssues"].append("r39_document_inventory_member_duplicate")
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
    documents = [{}] if invalid else []
    for group in grouped.values():
        individual = {"sourceIssues": []}
        build_one(state, run, group, individual)
        facts["sourceIssues"].extend(individual["sourceIssues"])
        if "documentContent" in individual:
            documents.append(individual["documentContent"])
    facts["documentContent"] = {"projectId": run["projectId"], "inventory": inventory, "documents": documents}
