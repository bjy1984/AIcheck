"""Corresponding record/report conclusion consistency; not re-evaluation of NDT acceptance."""
import re
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r39_tools import _refs, _text
from libs.review_tools.r40_records import KEYS, evaluate_r40_records


def _comparable_pairs(arguments):
    inventory = arguments.get("inventory")
    project = arguments.get("projectId")
    records, reports = arguments.get("records"), arguments.get("reports")
    if (not _text(project) or not isinstance(inventory, dict) or inventory.get("projectId") != project
            or inventory.get("complete") is not True or not _refs(inventory)
            or not isinstance(inventory.get("members"), list)
            or not isinstance(records, list) or not isinstance(reports, list)):
        return
    members = inventory["members"]
    for index, member in enumerate(members):
        if (not isinstance(member, dict) or member.get("projectId") != project
                or any(not _text(member.get(key)) for key in KEYS)):
            continue
        def matches(row, member=member):
            return isinstance(row, dict) and row.get("projectId") == project and all(row.get(key) == member[key] for key in KEYS)
        if sum(matches(row) for row in members) != 1:
            continue
        pair_records = [row for row in records if matches(row)]
        pair_reports = [row for row in reports if matches(row)]
        local = {"projectId": project, "inventory": {**inventory, "members": [member]},
                 "records": pair_records, "reports": pair_reports}
        if evaluate_r40_records(local)["result"] == "passed":
            yield index, pair_records[0], pair_reports[0]


def evaluate_r40_conclusions(arguments):
    correspondence = evaluate_r40_records(arguments)
    rows, refs = [], []
    if correspondence["result"] != "passed":
        status = correspondence["result"]
        rows.append({"code": "r40_conclusion_correspondence_unresolved", "result": status})
        refs = correspondence["evidenceRefs"]
    for index, record, report in _comparable_pairs(arguments):
        left, right = record.get("conclusion"), report.get("conclusion")
        left_refs, right_refs = _refs({"evidenceRefs": record.get("conclusionEvidenceRefs")}), _refs({"evidenceRefs": report.get("conclusionEvidenceRefs")})
        if (not _text(left) or not _text(right) or left not in {"合格", "不合格", "符合", "不符合"}
                or right not in {"合格", "不合格", "符合", "不符合"} or not left_refs or not right_refs
                or any(ref["documentVersionId"] != record.get("documentVersionId") for ref in left_refs)
                or any(ref["documentVersionId"] != report.get("documentVersionId") for ref in right_refs)
                or not any(re.search(r"(?<!\w)" + re.escape(left) + r"(?!\w)", ref["quotedText"]) for ref in left_refs)
                or not any(re.search(r"(?<!\w)" + re.escape(right) + r"(?!\w)", ref["quotedText"]) for ref in right_refs)):
            status = "evidence_insufficient"
        else:
            status = "passed" if (left in {"合格", "符合"}) == (right in {"合格", "符合"}) else "failed"
        rows.append({"code": f"r40_conclusion_pair_{index}", "result": status,
                     "recordConclusion": left, "reportConclusion": right})
        refs.extend([*left_refs, *right_refs])
    statuses = {row["result"] for row in rows}
    status = "failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "not_applicable" if statuses == {"not_applicable"} else "passed"
    output = result("evaluate_r40_conclusions", status,
        facts={"scope": "record_report_conclusion_consistency_only", "wholeRuleAcceptance": "not_evaluated",
               "conclusionChecks": rows, "evidenceVerified": False},
        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
        rule_version="r40-conclusion-consistency-v2")
    output["evidenceRefs"] = deepcopy(refs)
    return output
