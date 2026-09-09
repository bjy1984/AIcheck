"""Read explicit NDT labels without inferring conclusions or joining unrelated cells."""
from libs.ocr.ndt_procedure import extract_explicit_fields

LABELS = {
    "report_no": ["报告编号", "报告号"],
    "detection_method": ["检测方法"],
    "weld_no": ["焊口编号", "焊口号"],
    "detection_date": ["检测日期"],
    "report_date": ["报告日期"],
    "detection_ratio": ["检测比例"],
    "technical_grade": ["技术等级"],
    "evaluation_level": ["评定级别"],
    "acceptance_level": ["合格级别", "验收级别"],
    "conclusion": ["检测结论", "结论"],
}


def extract_report_fields(result, append_field):
    extract_explicit_fields(result, append_field, field_labels=LABELS, conflict_code="NDT_REPORT_LABEL_CONFLICT")
