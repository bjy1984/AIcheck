"""焊接段文档分类：判「这份文件是什么」，不是「它提到过什么」。

2026-09-11 拿生产 290 份解析结果实测出来的四类错判，每条用例对应一份真实文件：
- 裸 "wps" 标记命中评定报告里的「预焊接规程编号 pWPS-2023-01」，PQR 被判成 WPS；
- 「焊接工艺评定」不带「报告」时判不出来；
- 国家标准正文（TSG Z6002、GB 50236、JB/T 3223）被当成本工程的施工证据；
- 正文里提到「焊接工艺评定报告编号」就把工艺卡判成评定报告；目录/核查表同理。
"""
from __future__ import annotations

from typing import Any

from libs.review_orchestrator.r24_r34_facts import _document_kind


def _state(file_name: str, *, material_type_code: str = "", material_type_name: str = "") -> dict[str, Any]:
    return {
        "versions": [{"id": "DV-1", "documentId": "DOC-1"}],
        "documents": [
            {
                "id": "DOC-1",
                "fileName": file_name,
                "materialTypeCode": material_type_code,
                "materialTypeName": material_type_name,
            }
        ],
    }


def _parse(text: str) -> dict[str, Any]:
    return {"documentVersionId": "DV-1", "fragments": [{"text": text}]}


def test_评定报告里的预焊接规程编号不再把它判成wps():
    """9.1金辉焊接工艺评定20.pdf：正文是「焊接工艺评定报告 … 预焊接规程编号: pWPS-2023-01」。

    判成 wps 时节点 25 的 pqrItems、节点 32 的 qualificationReports 恒为 0。
    这类文件同时含 pWPS 与 PQR，wps_pqr 才能同时喂饱两边。
    """
    state = _state("9.1金辉焊接工艺评定20.pdf", material_type_code="ndt_report")
    text = "广东省金辉工业设备安装有限公司 焊接工艺评定报告 报告编号：HP/P-2023-01 预焊接规程编号: pWPS-2023-01 焊接方法： GTAW+SMAW"
    assert _document_kind(state, _parse(text)) == "wps_pqr"


def test_标题没有报告二字的评定也能判出来():
    """不锈钢氩弧焊HP022-2024焊接工艺评定.pdf：老写法要求整串「焊接工艺评定报告」，判成 None。"""
    state = _state("不锈钢氩弧焊HP022-2024焊接工艺评定.pdf", material_type_code="generic_review_material")
    assert _document_kind(state, _parse("单位名称:江苏三江机电工程有限公司 预焊接工艺规程编号:HPY022")) == "wps_pqr"
    bare = _state("某某焊接工艺评定.pdf")
    assert _document_kind(bare, _parse("评定结论 合格")) == "pqr"


def test_国家标准正文不是本工程的施工证据():
    """TSGZ6002-2010《焊接人员考核细则》.pdf 判成 wps、JB∕T 3223-2017 判成焊材质量证明，
    一旦被挂到节点上就会被当成工程证据去核。"""
    for file_name in (
        "TSGZ6002-2010《焊接人员考核细则》.pdf",
        "GB 50236-2011 现场设备、工业管道焊接工程施工规范.pdf",
        "JB∕T 3223-2017 焊接材料质量管理规程.pdf",
    ):
        state = _state(file_name, material_type_code="standard_reference")
        assert _document_kind(state, _parse("焊接工艺评定报告 焊材质量证明 预焊接工艺规程")) is None, file_name


def test_目录与核查表里提到的文件名不算数():
    """贵州化工交工资料.pdf 的目录写着「附件 4、焊接工艺评定」，
    0压力管道安装监检流程指引.docx 的核查表第 9 项是「焊接工艺评定」——都不是评定报告本身。"""
    dossier = _state("贵州化工交工资料.pdf", material_type_code="generic_review_material")
    text = "交工资料 施工单位：贵州化工建设有限责任公司 目录 1. 压力管道安装质量证明书 附件：3 施工方案 4、焊接工艺评定 5、X射线检测报告"
    assert _document_kind(dossier, _parse(text)) != "pqr"


def test_引用评定报告编号的工艺卡还是工艺卡():
    """9.2.焊接工艺卡.pdf 正文里有「焊接工艺评定报告编号 HP/P-2023-01」，那是引用不是自述。"""
    state = _state("9.2.焊接工艺卡.pdf")
    text = "焊接工艺卡 工程名称：珠海盈德化工区气站项目 工艺卡编号 JH-HJGYK-01 接头形式 见左图 焊接工艺评定报告编号 HP/P-2023-01"
    assert _document_kind(state, _parse(text)) == "wps"


def test_文档自身标注的物料类型要进入判定():
    """焊工名册.xlsx 的 documents.materialTypeCode 是 welder_certificate，
    可解析结果自己的 materialTypeCode 在生产里恒为 None，老写法够不着 documents 上那份。"""
    state = _state("焊工名册.xlsx", material_type_code="welder_certificate")
    assert _document_kind(state, _parse("序号 姓名 身份证号 焊工钢印号")) == "welder_certificate"
    by_name = _state("焊工清单.docx", material_type_code="generic_review_material")
    assert _document_kind(by_name, _parse("工程名称：珠海海瑞德制药有限公司 序号 姓名 代号 证号")) == "welder_certificate"
