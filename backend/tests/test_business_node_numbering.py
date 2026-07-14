from __future__ import annotations

from scripts.audit_business_node_numbering import audit, extract_checklist_nodes


def test_checklist_exposes_contiguous_engineering_nodes() -> None:
    nodes = extract_checklist_nodes()

    assert [item["nodeId"] for item in nodes] == list(range(1, 70))
    assert nodes[11]["name"] == "压力管道元件及安全附件制造单位的许可资质"
    assert nodes[23]["name"] == "焊工资格证及持证合格项目"
    assert nodes[67]["name"] == "吹扫、清洗"
    assert nodes[68]["name"] == "施工单位质量保证体系实施状况的评价"


def test_business_node_numbering_matches_checklist_everywhere() -> None:
    errors, stats = audit()

    assert stats["checklist_nodes"] == 69
    assert stats["rules"] == 69
    assert stats["clause_packages"] == 69
    assert errors == []
