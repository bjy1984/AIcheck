"""公式与表格的语义结构必须一路带到条款层。

## 为什么要专门锁住

标准里的计算式在 MinerU 里是 `equation` 块，正文就是一串 `$$ \\frac{...}{...} $$`。
这种文本撞上两条既有规则会被静默丢掉：

- `symbol_ascii_only`：长度不足 140 且全是 ASCII 符号 → 直接隔离，公式一条都不剩。
- `chunk_text` 的句读切分：`\\frac{S_1 - S_2}{S_1}` 从中间断开后再也渲染不回来。

两条都不报错，只是分块少了。所以用测试把「公式进得来、进来后还是完整的、
并且带着 LaTeX 和块类型」钉住。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.knowledge_indexing import (  # noqa: E402
    build_chunks_for_file,
    clause_from_chunk,
    embedding_text_for_chunk,
    quarantine_interference_reasons,
    structure_fields_for_unit,
)
from libs.mineru_ocr import _content_latex  # noqa: E402

EQUATION_LATEX = "$$\na = \\frac {S _ {1} - S _ {2}}{S _ {1}} \\times 100\\tag{1}\n$$"

FILE = {
    "id": "KF-KB-TEST",
    "sourceId": "KS-STANDARD-RULES",
    "fileName": "NB/T 47013.6-2015.pdf",
    "contextType": "standard_reference",
}


def _reocr_module():
    """按路径加载灌库脚本：scripts/ 不是包，正常 import 拿不到。"""
    path = BACKEND_ROOT / "scripts" / "reocr_standards_with_mineru.py"
    spec = importlib.util.spec_from_file_location("reocr_standards_with_mineru", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_mineru_equation_latex_comes_from_text_format():
    """MinerU 不给 latex 字段，只用 text_format 标注，必须认这种写法。"""
    assert _content_latex({"type": "equation", "text": EQUATION_LATEX, "text_format": "latex"}) == EQUATION_LATEX
    assert _content_latex({"type": "text", "text": "常规正文不是公式"}) == ""
    assert _content_latex({"latex": "E = mc^2"}) == "E = mc^2"


def test_equation_text_survives_symbol_only_quarantine():
    """同一段文本：当普通正文该被隔离，当公式块必须放行。"""
    assert "symbol_ascii_only" in quarantine_interference_reasons(EQUATION_LATEX)
    assert quarantine_interference_reasons(EQUATION_LATEX, block_type="equation") == []


def test_equation_chunk_keeps_latex_and_is_not_split():
    units = [
        {
            "text": EQUATION_LATEX,
            "pageNo": 21,
            "blockType": "equation",
            "latex": EQUATION_LATEX,
            "sectionPath": ["附录 A", "A.2 缺陷定量"],
            "sourceMethod": "mineru_ocr",
            "ocrEngine": "mineru",
        }
    ]
    chunks = build_chunks_for_file(FILE, units)
    assert len(chunks) == 1, "公式不能被切成多块"
    chunk = chunks[0]
    assert chunk["text"] == EQUATION_LATEX
    assert chunk["blockType"] == "equation"
    assert chunk["latex"] == EQUATION_LATEX
    assert chunk["pageNo"] == 21


def test_table_chunk_keeps_html_caption_and_structured_rows():
    html = (
        "<table><tr><th>钢管外径 D</th><th>通孔直径</th></tr>"
        "<tr><td>D≤27</td><td>1.20</td></tr></table>"
    )
    units = [
        {
            "text": "表 2 对比试样通孔直径及验收等级\n钢管外径 D 通孔直径\nD≤27 1.20",
            "pageNo": 8,
            "blockType": "table",
            "tableHtml": html,
            "caption": "表 2 对比试样通孔直径及验收等级",
            "sectionPath": ["5 检测工艺"],
        }
    ]
    chunk = build_chunks_for_file(FILE, units)[0]
    assert chunk["blockType"] == "table"
    assert chunk["tableHtml"] == html
    assert chunk["caption"].startswith("表 2")
    # 渲染路径要的是结构化行，不是 html
    assert chunk["tableColumns"] == ["钢管外径 D", "通孔直径"]
    assert chunk["tableRows"] == [{"钢管外径 D": "D≤27", "通孔直径": "1.20"}]


def test_retrieval_exposes_table_rows_not_html():
    """接口不下发 tableHtml——与 OCR 详情页同一条 XSS 约定。"""
    from libs.knowledge_retrieval import normalize_clause

    html = (
        "<table><tr><th>序号</th><th>相关因素</th></tr>"
        "<tr><td>1</td><td>材质</td></tr></table>"
    )
    clause = normalize_clause(
        {
            "clauseId": "CHK-1",
            "text": "表 1\n序号 相关因素\n1 材质",
            "blockType": "table",
            "tableHtml": html,
            "caption": "表 1",
        }
    )
    assert "tableHtml" not in clause
    assert clause["blockType"] == "table"
    assert clause["tableColumns"] == ["序号", "相关因素"]
    assert clause["tableRows"] == [{"序号": "1", "相关因素": "材质"}]
    assert clause["caption"] == "表 1"


def test_plain_text_chunk_has_no_structure_fields():
    """纯正文分块不该被塞上空的结构字段，否则「有没有结构」无从判断。"""
    units = [{"text": "焊缝表面应清除影响检测的氧化皮、油污及焊接飞溅物。" * 3, "pageNo": 3}]
    chunk = build_chunks_for_file(FILE, units)[0]
    for key in ("blockType", "latex", "tableHtml", "caption"):
        assert key not in chunk


def test_clause_carries_structure_and_block_type_tag():
    units = [
        {
            "text": EQUATION_LATEX,
            "pageNo": 21,
            "blockType": "equation",
            "latex": EQUATION_LATEX,
            "sectionPath": ["附录 A", "A.2 缺陷定量"],
        }
    ]
    chunk = build_chunks_for_file(FILE, units)[0]
    clause = clause_from_chunk(FILE, chunk, "inspection_kb@1.0.0")
    assert clause["blockType"] == "equation"
    assert clause["latex"] == EQUATION_LATEX
    assert "block_type:equation" in clause["tags"]
    assert clause["pageNo"] == 21


def test_embedding_text_wraps_formula_with_context():
    """裸 LaTeX 嵌入等于让模型读反斜杠，必须补上条款路径和「公式」字样。"""
    chunk = {
        "text": EQUATION_LATEX,
        "blockType": "equation",
        "sectionPath": ["NB/T 47013.6", "附录 A", "A.2 缺陷定量"],
    }
    text = embedding_text_for_chunk(chunk)
    assert "公式：" in text
    assert "A.2 缺陷定量" in text
    assert EQUATION_LATEX in text
    plain = {"text": "焊缝表面应清除氧化皮。"}
    assert embedding_text_for_chunk(plain) == "焊缝表面应清除氧化皮。"


def test_structure_fields_skip_blank_values():
    assert structure_fields_for_unit({"blockType": "", "latex": "  "}) == {}
    assert structure_fields_for_unit({"blockType": "Equation"}) == {"blockType": "equation"}


@pytest.mark.parametrize("caption_key", ["table_caption", "caption"])
def test_sidecar_table_becomes_its_own_fragment(caption_key):
    module = _reocr_module()
    items = [
        {"type": "text", "text": "5 检测工艺", "text_level": 1, "page_idx": 5},
        {"type": "text", "text": "检测前应清除被检件表面的氧化皮。", "page_idx": 5},
        {
            "type": "table",
            caption_key: ["表 1 相关因素"],
            "table_body": "<table><tr><td>序号</td><td>相关因素</td></tr><tr><td>1</td><td>材质</td></tr></table>",
            "page_idx": 5,
        },
    ]
    fragments = module.fragments_from_content_list(items)
    assert [item.get("blockType") for item in fragments] == [None, "table"]
    prose, table = fragments
    assert prose["sectionPath"] == ["5 检测工艺"]
    assert "氧化皮" in prose["text"]
    assert table["tableHtml"].startswith("<table>")
    assert table["caption"] == "表 1 相关因素"
    # 单元格必须垫开，否则 `序号` 和 `相关因素` 会粘成一个词
    assert "序号 相关因素" in table["text"]


def test_sidecar_equation_splits_prose_and_keeps_latex():
    module = _reocr_module()
    items = [
        {"type": "text", "text": "附录 A", "text_level": 1, "page_idx": 21},
        {"type": "text", "text": "缺陷面积百分比按下式计算：", "page_idx": 21},
        {"type": "equation", "text": EQUATION_LATEX, "text_format": "latex", "page_idx": 21},
        {"type": "text", "text": "式中 S1 为被检件面积。", "page_idx": 21},
        {"type": "page_number", "text": "21", "page_idx": 21},
    ]
    fragments = module.fragments_from_content_list(items)
    assert [item.get("blockType") for item in fragments] == [None, "equation", None]
    equation = fragments[1]
    assert equation["latex"] == EQUATION_LATEX
    assert equation["pageNo"] == 22, "page_idx 是 0 基，落库页号要 +1"
    assert equation["sectionPath"] == ["附录 A"]
    assert all(fragment["pageNo"] == 22 for fragment in fragments)


def test_retrieval_keeps_equation_candidate_and_latex():
    """检索入口用同一条隔离规则做二次过滤，公式曾在这里被整条滤掉。"""
    from libs.knowledge_retrieval import knowledge_clause_candidates

    state = {
        "knowledge_sources": [{"id": "KS-STANDARD-RULES", "version": "inspection_kb@1.0.0"}],
        "knowledge_files": [{**FILE, "sourceId": "KS-STANDARD-RULES"}],
        "knowledge_chunks": [
            {
                "id": "CHK-KF-KB-TEST-1",
                "fileId": "KF-KB-TEST",
                "text": EQUATION_LATEX,
                "blockType": "equation",
                "latex": EQUATION_LATEX,
                "pageNo": 21,
                "contextType": "standard_reference",
            }
        ],
    }
    candidates = knowledge_clause_candidates(state)
    equations = [item for item in candidates if item.get("blockType") == "equation"]
    assert equations, "公式分块必须能进检索候选"
    assert equations[0]["latex"] == EQUATION_LATEX
    assert equations[0]["text"] == EQUATION_LATEX


def test_retrieval_still_drops_symbol_noise_without_block_type():
    """放行只对结构块生效，普通噪声分块该滤掉的照旧滤掉。"""
    from libs.knowledge_retrieval import knowledge_clause_candidates

    state = {
        "knowledge_sources": [{"id": "KS-STANDARD-RULES", "version": "inspection_kb@1.0.0"}],
        "knowledge_files": [{**FILE, "sourceId": "KS-STANDARD-RULES"}],
        "knowledge_chunks": [
            {
                "id": "CHK-KF-KB-TEST-2",
                "fileId": "KF-KB-TEST",
                "text": "--- | --- | ---",
                "pageNo": 3,
                "contextType": "standard_reference",
            }
        ],
    }
    assert knowledge_clause_candidates(state) == []


def test_sidecar_drops_running_headers():
    module = _reocr_module()
    items = [
        {"type": "header", "text": "NB/T 47013.6—2015", "page_idx": 3},
        {"type": "footer", "text": "版权所有", "page_idx": 3},
        {"type": "page_number", "text": "4", "page_idx": 3},
        {"type": "text", "text": "检测人员应经过培训并取得资格证书。", "page_idx": 3},
    ]
    fragments = module.fragments_from_content_list(items)
    assert len(fragments) == 1
    assert fragments[0]["text"] == "检测人员应经过培训并取得资格证书。"
