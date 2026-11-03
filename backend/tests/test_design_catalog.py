"""图纸目录对照缺页：样本按 ECD202 整本施工图与 GDLNG 七张照片的结构缩写。"""
from __future__ import annotations

from libs.review_orchestrator.design_catalog import catalog_completeness, catalog_entries
from libs.review_tools.business_tools import check_document_set_completeness


def _table(*rows: list[str]) -> str:
    return "<table>" + "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows) + "</table>"


ECD_CATALOG = _table(
    ["序号", "文档名称", "页数", "文档编号", "备注"],
    ["序号", "文档名称", "7", "文档编号", "备注"],  # 合计行：首格不是序号，不收
    ["1", "图纸目录", "1", "HZ026Y-112-02-S000", "A4"],
    ["2", "安装设计说明", "3", "HZ026Y-112-02-S001", "A4"],
    ["3", "管道壁厚表", "2", "HZ026Y-112-02-S015", "A4"],
    ["4", "管道轴测图", "1", "HZ026Y-112-02-S250", "A2"],
)


def _page(page_no: int, text: str, html: str = "") -> dict:
    return {"pageNo": page_no, "text": text, **({"tableHtml": html} if html else {})}


def _bound_pdf(*, drop_first_thickness_page: bool) -> dict:
    pages = [
        _page(1, "图名 图纸目录 图号DWG NO. HZ026Y-112-02-S000 1/1", ECD_CATALOG),
        _page(2, "图号DWG NO. HZ026Y-112-02-S001 1/3 安装设计说明"),
        _page(3, "3.2 压力管道的设计执行 TSG 31-2025"),  # 图签没读出：归到前一份
        _page(4, "4.4 压力试验"),
        _page(5, "图号DWG NO. HZ026Y-112-02-S015 1/2 管道壁厚表"),
        _page(6, "图号DWG NO. HZ026Y-112-02-S015 2 / 2 DN25 32×2.5"),
        _page(7, "轴测图（图签没读出）"),
    ]
    if drop_first_thickness_page:
        pages = [page for page in pages if page["pageNo"] != 5]
    return {"documentVersionId": "DV-1", "fragments": pages}


def test_目录表读出编号和页数_合计行不收():
    entries = catalog_entries(_bound_pdf(drop_first_thickness_page=False))
    assert [(item["documentNo"][-4:], item["pages"]) for item in entries] == [("S000", 1), ("S001", 3), ("S015", 2), ("S250", 1)]


def test_整本PDF按装订顺序归页_交全时不报缺():
    result = catalog_completeness([_bound_pdf(drop_first_thickness_page=False)], {"DV-1": "H1"})
    assert result["catalogPageTotal"] == 7 and result["submittedPageCount"] == 7
    assert result["missingPageCount"] == 0 and result["shortDocuments"] == []


def test_整本PDF少一页_指出是哪一份():
    # ECD202：目录合计 38、PDF 37 页，壁厚表只见「2/2」
    result = catalog_completeness([_bound_pdf(drop_first_thickness_page=True)], {"DV-1": "H1"})
    assert result["missingPageCount"] == 1
    assert [(item["documentNo"][-4:], item["catalogPages"], item["submittedPages"]) for item in result["shortDocuments"]] == [("S015", 2, 1)]


def test_同一份文件交两次只算一份():
    once = _bound_pdf(drop_first_thickness_page=True)
    twice = {**once, "documentVersionId": "DV-2"}
    result = catalog_completeness([once, twice], {"DV-1": "H1", "DV-2": "H1"})
    assert result["submittedPageCount"] == 6 and result["missingPageCount"] == 1


def test_照片之间没有顺序_读不出图号的只记认不出():
    catalog = _table(["序号", "名称", "图号或编号", "版次", "自然张数"],
                     ["1", "工艺图纸目录", "QX201903S-13-Y-00", "1", "1"],
                     ["2", "工艺设计说明书", "QX201903S-13-Y-01", "1", "6"],
                     ["3", "管道特性表", "QX201903S-13-Y-07", "1", "1"])
    photos = [
        {"documentVersionId": "P1", "fragments": [_page(1, "图纸编号DWG.No. QX201903S-13-Y-00", catalog)]},
        # 正文引用了特性表编号，但图签里的才是本页编号
        {"documentVersionId": "P2", "fragments": [_page(1, "图纸编号DWG. No. QX201903S-13-Y-01 共6页 详见管道特性表 (QX201903S-13-Y-07)")]},
        {"documentVersionId": "P3", "fragments": [_page(1, "（读不出字）")]},
    ]
    result = catalog_completeness(photos, {})
    assert result["catalogPageTotal"] == 8 and result["submittedPageCount"] == 3
    assert result["missingPageCount"] == 5 and result["unplacedPageCount"] == 1
    assert {item["documentNo"][-4:]: item["submittedPages"] for item in result["shortDocuments"]} == {"Y-01": 1, "Y-07": 0}


def test_没有目录不出结论():
    assert catalog_completeness([{"documentVersionId": "V", "fragments": [_page(1, "安装设计说明")]}], {}) is None


def _tool(catalog: dict | None) -> dict:
    return check_document_set_completeness({
        "requiredDocumentTypes": ["drawing_catalog"], "uploadedDocumentTypes": ["drawing_catalog"],
        "parseableDocumentTypes": ["drawing_catalog"], "catalogCompleteness": catalog,
    })


def test_缺页按证据不足_不判不符合_缺什么写清楚():
    catalog = catalog_completeness([_bound_pdf(drop_first_thickness_page=True)], {"DV-1": "H1"})
    output = _tool(catalog)
    assert output["result"] == "evidence_insufficient"
    item = next(check for check in output["checks"] if check["code"] == "catalog_pages_submitted")
    assert item["missing"] is True and item["reason"] == "catalog_pages_not_all_submitted"
    assert item["actual"]["shortDocuments"][0]["name"] == "管道壁厚表"


def test_目录交全或没有目录时结论不变():
    assert _tool(catalog_completeness([_bound_pdf(drop_first_thickness_page=False)], {"DV-1": "H1"}))["result"] == "passed"
    assert _tool(None)["result"] == "passed"
