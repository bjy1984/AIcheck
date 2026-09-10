"""Compare uniquely identified uses without treating supplied rows as a complete inventory."""
from copy import deepcopy

from libs.review_tools.r11_approval_timing import SCOPE, approval_timing
from libs.review_tools.r39_tools import _refs


def usage_checks(scope, approval, usages, inventory):
    rows = []
    groups = {}
    malformed = not isinstance(usages, list)
    for usage in usages if isinstance(usages, list) else []:
        identity = usage.get("usageId") if isinstance(usage, dict) else None
        if not isinstance(identity, str) or not identity.strip():
            malformed = True
            continue
        groups.setdefault(identity, []).append(usage)
    ids = inventory.get("usageIds") if isinstance(inventory, dict) else None
    valid_inventory = (isinstance(inventory, dict) and inventory.get("complete") is True
        and all(inventory.get(key) == scope.get(key) for key in SCOPE) and bool(_refs(inventory))
        and isinstance(ids, list) and bool(ids)
        and all(isinstance(value, str) and value.strip() for value in ids))
    if valid_inventory:
        valid_inventory = len(ids) == len(set(ids))
    complete = (valid_inventory and not malformed and set(ids) == set(groups)
                and all(len(items) == 1 for items in groups.values()))
    rows.append({"code": "r11_usage_inventory", "result": "passed" if complete else "evidence_insufficient",
                 "evidenceRefs": deepcopy(_refs(inventory)) if isinstance(inventory, dict) else []})
    # An incomplete inventory must not erase a demonstrated late approval. Duplicate
    # identities are ambiguous, however: never choose either row as the correct one.
    for identity, items in groups.items():
        row = approval_timing(scope, approval, items[0] if len(items) == 1 else None)
        row["usageId"] = identity
        rows.append(row)
    if valid_inventory:
        for identity in ids:
            if identity not in groups:
                row = approval_timing(scope, approval, None)
                row["usageId"] = identity
                rows.append(row)
    return rows
