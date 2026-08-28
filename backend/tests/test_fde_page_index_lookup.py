"""标准库列表页的页索引匹配：索引版必须与全扫描版同集同序。

全扫描版 60 文件 × 1.9 万节点 = 456 万次取值，实测 1.7 秒；
索引版一次建表。两个实现并存（详情页仍用全扫描版），等价性由本测试钉死。
"""

from __future__ import annotations

from libs.fde_console_views import (
    fde_standard_file_page_index_nodes,
    fde_standard_file_page_index_nodes_indexed,
    fde_standard_page_index_lookup,
)


def _nodes() -> list[dict]:
    return [
        # 文件 F1：nodeId 直连 + 子节点
        {"id": "N1", "nodeId": "F1", "sourceRelativePath": "a/f1.pdf"},
        {"id": "N2", "parentNodeId": "N1", "sourceRelativePath": ""},
        # 文件 F2：只有 sourceRelativePath 匹配（无 nodeId 直连）
        {"id": "N3", "sourceRelativePath": "b/f2.pdf"},
        {"id": "N4", "parentNodeId": "N3", "sourceRelativePath": "b/f2.pdf"},
        # 无关节点
        {"id": "N5", "nodeId": "F9", "sourceRelativePath": "c/f9.pdf"},
        {"id": "N6", "parentNodeId": "N5", "sourceRelativePath": ""},
        # 文件 F3：路径匹配且带 parentNodeId（种子集合的第二个分支）
        {"id": "N7", "parentNodeId": "NX", "sourceRelativePath": "d/f3.pdf"},
        {"id": "N8", "parentNodeId": "N7", "sourceRelativePath": ""},
    ]


def test_indexed_variant_matches_scan_variant_for_all_branches() -> None:
    nodes = _nodes()
    lookup = fde_standard_page_index_lookup(nodes)
    files = [
        {"id": "F1", "sourceRelativePath": "a/f1.pdf"},
        {"id": "F2", "sourceRelativePath": "b/f2.pdf"},
        {"id": "F3", "sourceRelativePath": "d/f3.pdf"},
        {"id": "F-NONE", "sourceRelativePath": "zz/none.pdf"},
        {"id": "F-NOPATH", "sourceRelativePath": ""},
    ]
    for file in files:
        scan = fde_standard_file_page_index_nodes(file, nodes)
        indexed = fde_standard_file_page_index_nodes_indexed(file, lookup)
        assert [n["id"] for n in indexed] == [n["id"] for n in scan], file["id"]
