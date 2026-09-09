"""Join sourced first-use facts by instruction revision, object and event."""
from libs.review_tools.r39_tools import IDENTITY_FIELDS, _text


def _single_input(run, groups, clean):
    if len(groups["applications"]) != 1 or any(len(groups[name]) > 1 for name in ("bases", "validations")):
        return None
    application = clean(groups["applications"][0])
    if application.get("projectId") != run["projectId"]:
        return None
    value = {"projectId": run["projectId"], "scope": {key: application.get(key) for key in IDENTITY_FIELDS}, "application": application}
    for name, key in (("bases", "basis"), ("validations", "validation")):
        if groups[name]:
            value[key] = clean(groups[name][0])
    return value


def application_input(run, groups, clean):
    inventories, members = groups["applicationInventories"], groups["applicationMembers"]
    if not inventories and not members:
        return _single_input(run, groups, clean)
    if len(inventories) != 1:
        return None
    inventory = clean(inventories[0])
    inventory["members"] = [clean(row) for row in members]
    names = ("applications", "bases", "validations")
    grouped = {}
    for member in inventory["members"]:
        if any(not _text(member.get(field)) for field in IDENTITY_FIELDS):
            return None
        key = tuple(member[field] for field in IDENTITY_FIELDS)
        if key in grouped:
            return None
        grouped[key] = {name: [] for name in names}
    invalid = False
    for name in names:
        for row in groups[name]:
            if any(not _text(row.get(field)) for field in IDENTITY_FIELDS):
                invalid = True
                continue
            key = tuple(row[field] for field in IDENTITY_FIELDS)
            if key not in grouped:
                invalid = True
                continue
            grouped[key][name].append(row)
    applications = [{}] if invalid else []
    for group in grouped.values():
        value = _single_input(run, group, clean)
        if value is not None:
            applications.append(value)
    return {"projectId": run["projectId"], "inventory": inventory, "applications": applications}
