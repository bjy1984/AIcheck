"""Synthetic handoff fixtures/control for the loopback-only browser test bridge."""
import hashlib
from pathlib import Path

import fitz

from libs.business_pack import load_business_pack
from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.runtime_tools import runtime_tool_catalog
from libs.review_workstations import freeze_station

PROJECT = "P-2026-HDCP-001"
SOURCE = "RR-LAB-HANDOFF-SOURCE"
TARGET = "RR-LAB-HANDOFF-TARGET"
VERSION = "VER-LAB-HANDOFF"


def seed(repo, originals: Path):
    file = originals / "handoff.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 70), "SYNTHETIC TEST ONLY - NOT AN INSPECTION RECORD")
        page.insert_text((40, 110), "Object W-101 / Event EV-1 / Repair round 1")
        page.insert_text((40, 150), "Handoff request: verify the matching reinspection event.")
        pdf.save(file)
    repo.state["documents"].append({
        "id": "DOC-LAB-HANDOFF", "projectId": PROJECT, "tenantId": "TENANT-DEFAULT",
        "currentVersionId": VERSION, "fileName": "handoff.pdf", "fileStatus": "已上传",
        "fileType": "pdf", "poolSubmissionStatus": "已提交",
    })
    repo.state["versions"].append({
        "id": VERSION, "documentId": "DOC-LAB-HANDOFF", "tenantId": "TENANT-DEFAULT",
        "fileName": "handoff.pdf", "fileType": "application/pdf", "versionNo": 1,
        "hash": hashlib.sha256(file.read_bytes()).hexdigest(), "storageKey": "local://handoff.pdf",
    })
    repo.state["ocr_parse_results"].append({
        "id": "OCR-LAB-HANDOFF", "documentVersionId": VERSION, "tenantId": "TENANT-DEFAULT",
        "pages": [{"pageNo": 1, "text": "SYNTHETIC TEST ONLY: W-101 / EV-1 / repair round 1"}],
    })
    pack = load_business_pack("engineering_inspection_v1")
    for run_id, node in ((SOURCE, 24), (TARGET, 35)):
        run = {
            "id": run_id, "projectId": PROJECT, "tenantId": "TENANT-DEFAULT", "nodeId": node,
            "businessPackId": pack["id"], "inputHash": run_id,
            "inputDocumentVersionIds": [VERSION] if node == 24 else [],
            "workstationSnapshot": freeze_station(node, pack, runtime_tool_catalog()),
        }
        run["documentScopeSnapshot"] = freeze_document_scope(run, repo.state)
        repo.state["review_runs"].append(run)


def control(repo, action):
    if action == "change-source":
        parse = next(row for row in repo.state["ocr_parse_results"] if row.get("id") == "OCR-LAB-HANDOFF")
        parse["pages"][0]["text"] += " MODIFIED"
    elif action == "progress-target":
        target = repo.find_one("review_runs", TARGET)
        target.update(status="running", outputHash="SYNTHETIC-TARGET-OUTPUT",
                      findingDrafts=[{"id": "SYNTHETIC-TARGET-FINDING"}])
    elif action == "restrict-source":
        member = next(row for row in repo.state["project_members"] if row.get("projectId") == PROJECT
                      and row.get("userId") == "USER-INSPECTION-001")
        member["nodeScope"] = [35]
    else:
        raise ValueError("unknown synthetic handoff action")
