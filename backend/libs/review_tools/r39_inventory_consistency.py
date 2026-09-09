"""Cross-check declared R39 inventories without certifying their real-world completeness."""
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import result
from libs.review_tools.r39_approval import SCOPE_FIELDS as APPROVAL_FIELDS
from libs.review_tools.r39_content import SCOPE_FIELDS as DOCUMENT_FIELDS
from libs.review_tools.r39_reference import SCOPE_FIELDS as REFERENCE_FIELDS
from libs.review_tools.r39_tools import IDENTITY_FIELDS, _refs, _text

INVENTORIES = {"referenceInventory": REFERENCE_FIELDS, "documentInventory": DOCUMENT_FIELDS,
               "approvalInventory": APPROVAL_FIELDS, "applicationInventory": IDENTITY_FIELDS}


def evaluate_r39_inventory_consistency(arguments):
    issues, refs, inventories = [], [], {}

    def issue(code, **details):
        issues.append({"code": code, **details})

    def finish():
        output = result("evaluate_r39_inventory_consistency", "evidence_insufficient" if issues else "passed",
            facts={"scope": "declared_inventory_consistency_only", "issues": issues,
                   "wholeRuleAcceptance": "not_evaluated", "realWorldCompleteness": "not_evaluated",
                   "evidenceVerified": False}, checks=[], rule_version="r39-cross-inventory-v1")
        output["evidenceRefs"] = deepcopy(refs)
        return output

    project = arguments.get("projectId")
    for name, fields in INVENTORIES.items():
        inventory = arguments.get(name)
        if (not _text(project) or not isinstance(inventory, dict) or inventory.get("projectId") != project
                or inventory.get("complete") is not True or not _refs(inventory)
                or not isinstance(inventory.get("members"), list) or not inventory["members"]):
            issue("r39_inventory_missing_or_incomplete", inventory=name)
            continue
        refs.extend(_refs(inventory))
        values = {}
        for member in inventory["members"]:
            if (not isinstance(member, dict) or member.get("projectId") != project
                    or any(not _text(member.get(field)) for field in fields) or not _refs(member)):
                issue("r39_inventory_member_invalid", inventory=name)
                continue
            key = tuple(member[field] for field in fields)
            if key in values:
                issue("r39_inventory_member_duplicate", inventory=name, identity=dict(zip(fields, key, strict=True)))
            values[key] = member
            refs.extend(_refs(member))
        inventories[name] = values
    if issues:
        return finish()

    def document_key(member, prefix=None):
        if prefix:
            return (member["projectId"], member["organizationId"], member[prefix + "DocumentId"],
                    member[prefix + "DocumentVersionId"], prefix, member["method"])
        return tuple(member[key] for key in DOCUMENT_FIELDS)

    documents = set(inventories["documentInventory"])
    for member in inventories["documentInventory"].values():
        if member["documentKind"] not in {"procedure", "instruction"}:
            issue("r39_inventory_document_kind_invalid", document=document_key(member))
    references = set()
    for member in inventories["referenceInventory"].values():
        references.update(document_key(member, prefix) for prefix in ("instruction", "procedure"))
    approvals = {document_key(member) for member in inventories["approvalInventory"].values()}
    for name, values in (("referenceInventory", references), ("approvalInventory", approvals)):
        for key in sorted(documents - values):
            issue("r39_document_missing_from_inventory", inventory=name, document=dict(zip(DOCUMENT_FIELDS, key, strict=True)))
        for key in sorted(values - documents):
            issue("r39_document_missing_content_inventory", inventory=name, document=dict(zip(DOCUMENT_FIELDS, key, strict=True)))

    links = arguments.get("applicationDocumentLinks")
    if not isinstance(links, list) or not links:
        issue("r39_application_document_links_missing")
        return finish()
    linked, instruction_versions = {}, {}
    for link in links:
        fields = (*IDENTITY_FIELDS, "instructionDocumentId", "instructionDocumentVersionId")
        if (not isinstance(link, dict) or any(not _text(link.get(field)) for field in fields)
                or link.get("projectId") != project or not _refs(link)):
            issue("r39_application_document_link_invalid")
            continue
        key = tuple(link[field] for field in IDENTITY_FIELDS)
        if key not in inventories["applicationInventory"]:
            issue("r39_application_link_not_in_inventory", application=dict(zip(IDENTITY_FIELDS, key, strict=True)))
        if key in linked:
            issue("r39_application_document_link_duplicate", application=dict(zip(IDENTITY_FIELDS, key, strict=True)))
        target = document_key(link, "instruction")
        linked[key] = target
        refs.extend(_refs(link))
        if target not in documents:
            issue("r39_application_document_missing_content", document=dict(zip(DOCUMENT_FIELDS, target, strict=True)))
        identity = tuple(link[field] for field in ("projectId", "organizationId", "instructionId", "instructionVersion", "method"))
        instruction_versions.setdefault(identity, set()).add(target)
    for identity, targets in instruction_versions.items():
        if len(targets) > 1:
            issue("r39_instruction_revision_maps_to_multiple_documents", instruction=list(identity))
    for key in sorted(set(inventories["applicationInventory"]) - linked.keys()):
        issue("r39_application_document_link_missing", application=dict(zip(IDENTITY_FIELDS, key, strict=True)))
    for key in sorted({key for key in documents if key[4] == "instruction"} - set(linked.values())):
        issue("r39_instruction_has_no_declared_application", document=dict(zip(DOCUMENT_FIELDS, key, strict=True)))
    return finish()
