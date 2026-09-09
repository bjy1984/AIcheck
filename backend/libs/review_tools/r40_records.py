"""R40 declared inspection events: record/report correspondence, not technical adequacy."""
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r39_tools import _refs, _text

KEYS = ("objectId", "method", "eventId")


def evaluate_r40_records(arguments):
    checks, refs = [], []

    def add(code, status):
        checks.append(check(code, status == "passed", status, "passed"))
        statuses.append(status)

    statuses = []
    project = arguments.get("projectId")
    inventory = arguments.get("inventory")
    if (not _text(project) or not isinstance(inventory, dict) or inventory.get("projectId") != project
            or inventory.get("complete") is not True or not _refs(inventory)):
        add("r40_event_inventory_missing", "evidence_insufficient")
    else:
        refs.extend(_refs(inventory))
        members = inventory.get("members")
        records, reports = arguments.get("records"), arguments.get("reports")
        if not isinstance(members, list) or not members or not isinstance(records, list) or not isinstance(reports, list):
            add("r40_record_report_inventory_missing", "evidence_insufficient")
        else:
            seen, used_records, used_reports = set(), set(), set()
            for index, member in enumerate(members):
                key = tuple(member.get(field) for field in KEYS) if isinstance(member, dict) else ()
                if (len(key) != len(KEYS) or any(not _text(value) for value in key) or key in seen
                        or member.get("projectId") != project or not _refs(member)):
                    add(f"r40_event_{index}_identity_ambiguous", "evidence_insufficient")
                    continue
                seen.add(key)
                refs.extend(_refs(member))
                applicable = member.get("applicable")
                if type(applicable) is not bool:
                    add(f"r40_event_{index}_applicability_unknown", "evidence_insufficient")
                    continue
                pairs = []
                for rows, used in ((records, used_records), (reports, used_reports)):
                    matches = [(i, row) for i, row in enumerate(rows) if isinstance(row, dict)
                               and row.get("projectId") == project and tuple(row.get(field) for field in KEYS) == key]
                    used.update(i for i, _ in matches)
                    pairs.append([row for _, row in matches])
                if not applicable:
                    add(f"r40_event_{index}_excluded", "not_applicable" if not any(pairs) else "evidence_insufficient")
                    continue
                if any(len(rows) != 1 for rows in pairs):
                    add(f"r40_event_{index}_record_report_missing_or_ambiguous", "evidence_insufficient")
                    continue
                record, report = pairs[0][0], pairs[1][0]
                if not _refs(record) or not _refs(report) or not _text(record.get("recordId")) or not _text(report.get("recordId")):
                    add(f"r40_event_{index}_source_missing", "evidence_insufficient")
                    continue
                refs.extend([*_refs(record), *_refs(report)])
                add(f"r40_event_{index}_record_reference", "passed" if record["recordId"] == report["recordId"] else "failed")
            if len(used_records) != len(records) or len(used_reports) != len(reports):
                add("r40_records_outside_declared_inventory", "evidence_insufficient")
    selection_issues = arguments.get("selectionIssues", [])
    if selection_issues:
        add("r40_selected_source_coverage_incomplete", "evidence_insufficient")
    status = ("failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses
              else "not_applicable" if set(statuses) == {"not_applicable"} else "passed")
    output = result("evaluate_ndt_process", status, checks=checks, rule_version="r40-record-report-correspondence-v1",
                    facts={"scope": "declared_record_report_correspondence_only", "wholeRuleAcceptance": "not_evaluated",
                           "evidenceVerified": False, "selectionIssues": deepcopy(selection_issues), "pendingCapabilities": ["technical_parameters", "design_requirements", "report_results"]})
    output["evidenceRefs"] = deepcopy(refs)
    return output
