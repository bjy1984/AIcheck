from scripts.knowledge_quality_audit import bbox_applicable


def test_bbox_is_required_for_page_grounded_chunks() -> None:
    assert bbox_applicable(
        {
            "contextType": "standard_reference",
            "sourceMethod": "remote_ocr_fragments",
        }
    )
    assert bbox_applicable(
        {
            "contextType": "standard_reference",
            "sourceMethod": "pdf_text_layer",
        }
    )


def test_bbox_is_not_applicable_to_non_spatial_sources() -> None:
    assert not bbox_applicable(
        {
            "contextType": "business_rule_context",
            "sourceMethod": "deterministic_text_parse",
        }
    )
    assert not bbox_applicable(
        {
            "contextType": "standard_reference",
            "sourceMethod": "deterministic_docx_parse",
        }
    )
