"""Explicit source identity labels only; never infer an event from dates or weld numbers."""
from libs.ocr.ndt_procedure import extract_explicit_fields

LABELS = {
    "record_no": ["本记录编号", "检测记录编号"],
    "referenced_record_no": ["引用记录编号", "依据记录编号"],
    "detection_event_no": ["检测事件编号", "检测任务编号"],
    "ndt_document_kind": ["文件类型"],
}


def extract_record_identity(result, append_field):
    extract_explicit_fields(result, append_field, field_labels=LABELS, conflict_code="NDT_RECORD_IDENTITY_CONFLICT")
