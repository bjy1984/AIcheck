from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from .catalog import DocumentSpec, load_catalog


TEST_WARNING = "测试专用／合成资料／不得用于真实工程"
PROJECT_NAME = (
    "珠海恒基达鑫国际化工仓储股份有限公司"
    "一、二期装车站新增两套卸车系统项目"
)

STANDARDS = [
    [
        "TSG D7006—2020", "压力管道监督检验规则", "安装监督检验资料结构",
        "项目来源与现行查新", "2020-09-01", "B00／V00",
        "https://www.samr.gov.cn/cms_files/filemanager/samr/www/samrnew/tzsbj/tzgg/zjwh/202005/W020200521635020831543.pdf",
    ],
    [
        "TSG 31—2025", "工业管道安全技术规程", "工业管道设计、安装、检验与使用",
        "2026测试记录日期现行", "2026-01-01", "S01—S06／V00",
        "https://www.samr.gov.cn/tzsbj/tzgg/zjwh/art/2026/art_ed12d58e1b4a4f668ff80268b375ef59.html",
    ],
    [
        "TSG 92—2026", "承压类特种设备安全附件安全技术规程", "安全附件设计、选用、安装与校验",
        "2026测试记录日期现行", "2026-07-01", "S05",
        "https://www.samr.gov.cn/tzsbj/zcfg/aqjsgf/aqjsgf/art/2026/art_24e7ccdf5d4d4176bc2a65ab34ec2842.html",
    ],
    [
        "TSG 08—2026", "特种设备使用管理规则", "使用登记与质量安全主体责任",
        "2026测试记录日期现行", "2026-05-01", "V00／R69",
        "https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/tzsbs/art/2026/art_ccfd987974c9490ab5d8c0792593f1d3.html",
    ],
    [
        "GB/T 20801.1—2025", "压力管道规范 第1部分：工业管道", "2026测试设计与通用要求",
        "现行；全部代替2020版六部分", "2026-05-01", "S01—S06",
        "https://std.samr.gov.cn/gb/search/gbDetailed?id=42BA7D06A208E936E06397BE0A0ACDC9",
    ],
    [
        "GB/T 20801.1～6—2020", "压力管道规范 工业管道（原六部分）", "2021项目设计基准",
        "仅保留项目日期适用事实", "2020-10-01", "B00来源事实",
        "https://std.samr.gov.cn/search/stdPage?q=GB%2FT20801",
    ],
    [
        "NB/T 47014—2023", "承压设备焊接工艺评定", "2026测试焊接工艺评定",
        "测试记录日期现行", "2024-06-28", "S02／S03",
        "https://zfxxgk.nea.gov.cn/1310759283_17047031765681n.pdf",
    ],
    [
        "NB/T 47013.2—2015", "承压设备无损检测 第2部分：射线检测", "2021原始RT报告与测试RT",
        "来源报告明确采用；测试适用性查新", "2015-09-01", "B00／S03／S06",
        "files/交工资料.pdf",
    ],
    [
        "NB/T 47013.4—2015", "承压设备无损检测 第4部分：磁粉检测", "测试MT检测",
        "按测试日期适用性核验", "2015-09-01", "S06",
        "files/TSG D7006-2020 压力管道监督检验规则.pdf",
    ],
    [
        "NB/T 47013.8—2025", "承压设备无损检测 第8部分：泄漏检测", "泄漏检测",
        "测试记录日期现行", "2026-06-18", "S06",
        "https://www.nea.gov.cn/20251230/ef9d5d59dc9e4cffa7c712d516967857/20251230ef9d5d59dc9e4cffa7c712d516967857_11f4145a70726d44bfaad3650bf12c570d.pdf",
    ],
    [
        "TSG Z6002—2010", "特种设备焊接操作人员考核细则", "本包记录日期焊工资格",
        "2026-07-15仍有效", "2011-02-01", "B00／S01—S06",
        "files/TSGZ6002-2010《焊接人员考核细则》.pdf",
    ],
    [
        "TSG Z6002—2026", "特种设备焊接操作人员考核细则", "后续焊工资格规则",
        "已发布；本包日期尚未实施", "2026-08-01", "版本提醒",
        "https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/tzsbs/art/2026/art_4153ad05135445e1b342d6a80814ad72.html",
    ],
    [
        "GB 50235—2010", "工业金属管道工程施工规范", "施工与安装",
        "项目与测试通用", "2011-06-01", "B00／S01—S06",
        "files/GB 50235-2010 工业金属管道工程施工规范.pdf",
    ],
    [
        "GB 50236—2011", "现场设备、工业管道焊接工程施工规范", "焊接施工",
        "项目与测试通用", "2011-10-01", "B00／S02／S03／S06",
        "files/GB 50236-2011 现场设备、工业管道焊接工程施工规范.pdf",
    ],
]


def _approval_rows(date: str) -> list[dict[str, str]]:
    return [
        {
            "role": "编制",
            "name": "测试设计负责人甲",
            "date": date,
            "record": "电子记录（测试）",
        },
        {
            "role": "校核",
            "name": "测试校核负责人乙",
            "date": date,
            "record": "电子记录（测试）",
        },
        {
            "role": "批准",
            "name": "测试批准负责人丙",
            "date": date,
            "record": "电子记录（测试）",
        },
    ]


def _base_content(spec: DocumentSpec) -> dict[str, Any]:
    node_text = "、".join(f"R{node:02d}" for node in spec.r_nodes) or "目录控制"
    return {
        "logical_id": spec.logical_id,
        "folder": spec.folder,
        "title": spec.title,
        "document_number": spec.document_number,
        "revision": spec.revision,
        "date": spec.date,
        "file_stem": spec.file_stem,
        "source_format": spec.source_format,
        "r_nodes": list(spec.r_nodes),
        "related_lines": list(spec.related_lines),
        "related_welds": list(spec.related_welds),
        "related_materials": list(spec.related_materials),
        "sections": [
            {
                "heading": "1 文件目的与适用范围",
                "paragraphs": [
                    f"本文件属于{PROJECT_NAME}的业务完整性验收测试资料，"
                    f"用于支撑{node_text}节点的资料链验证。",
                    "资料以既有施工图数据为核心；无法从来源确认的单位、人员、"
                    "证书号和记录编号均使用TEST前缀，不构成真实工程凭证。",
                ],
            },
            {
                "heading": "2 对象与追溯关系",
                "key_values": [
                    ["关联管线", "、".join(spec.related_lines) or "不直接绑定"],
                    ["关联焊口", "、".join(spec.related_welds) or "不直接绑定"],
                    ["关联材料", "、".join(spec.related_materials) or "不直接绑定"],
                    ["节点范围", node_text],
                ],
            },
            {
                "heading": "3 结论",
                "paragraphs": [
                    "经测试资料链检查，本文件所列对象、记录和关联编号可追溯，"
                    "最终状态合格；过程异常按对应分册的闭环记录执行。",
                    TEST_WARNING,
                ],
            },
        ],
        "tables": [],
        "references": [
            "QX201903S-13-Y-07／QX201903S-13-Y-10（既有施工图来源）",
            "M00-STD-001 标准版本台账",
            "V00-R01-R69资料覆盖矩阵",
        ],
        "approvals": _approval_rows(spec.date),
        "workbook": {
            "sheets": [
                {
                    "name": "记录",
                    "headers": ["序号", "对象", "检查内容", "结果", "追溯编号"],
                    "rows": [
                        [
                            1,
                            "、".join(spec.related_lines[:3]) or spec.logical_id,
                            spec.title,
                            "合格",
                            spec.document_number,
                        ]
                    ],
                }
            ]
        },
    }


def _table(title: str, headers: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"title": title, "headers": headers, "rows": rows}


def _sheet(name: str, headers: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"name": name, "headers": headers, "rows": rows}


def _add_terms(content: dict[str, Any], heading: str, terms: list[str]) -> None:
    content["sections"].insert(
        -1,
        {
            "heading": heading,
            "bullets": terms,
        },
    )


def _all_master_sheets(master: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _sheet(
            "项目",
            ["字段", "内容"],
            [
                ["项目名称", master["project"]["name"]],
                ["建设单位", master["project"]["owner"]],
                ["设计单位", master["project"]["designOrganization"]],
                ["图号前缀", master["project"]["drawingPrefix"]],
                ["管道级别", master["project"]["pipelineClass"]],
                ["资料包日期", master["project"]["testPackDate"]],
            ],
        ),
        _sheet(
            "管线",
            ["管线号", "场景", "规格", "设计压力MPa", "设计温度℃", "材料批次"],
            [
                [
                    row["id"],
                    row["scenario"],
                    row["specification"],
                    row["designPressureMpa"],
                    row["designTemperatureC"],
                    "、".join(row["materialBatchIds"]),
                ]
                for row in master["lines"]
            ],
        ),
        _sheet(
            "焊口",
            ["焊口号", "场景", "管线号", "材料批次", "完成日期", "状态", "返修次数"],
            [
                [
                    row["id"],
                    row["scenario"],
                    row["lineId"],
                    row["materialBatchId"],
                    row["completedOn"],
                    row["status"],
                    row.get("repairCount", 0),
                ]
                for row in master["welds"]
            ],
        ),
        _sheet(
            "材料",
            ["批次号", "场景", "牌号", "标准", "炉批号"],
            [
                [row["id"], row["scenario"], row["grade"], row["standard"], row["heatNumber"]]
                for row in master["materialBatches"]
            ],
        ),
        _sheet(
            "身份引用",
            ["编号", "名称", "角色", "资料属性"],
            [
                [row["id"], row["name"], row["role"], "合成" if row["synthetic"] else "来源复用"]
                for row in master["organizations"]
            ]
            + [
                [row["id"], row["name"], row["role"], "合成" if row["synthetic"] else "来源复用"]
                for row in master["people"]
            ],
        ),
    ]


def _customize_m00(content: dict[str, Any], spec: DocumentSpec,
                   master: dict[str, Any], catalog_rows: list[dict[str, Any]],
                   requirement_rows: list[dict[str, Any]]) -> None:
    if spec.logical_id == "M00-README-001":
        _add_terms(
            content,
            "3 使用说明",
            [
                "基础项目B00保持既有项目名、单位、图号和原设计参数不变。",
                "S01—S06采用测试专用设计变更、独立管段号和材料记录，互不污染。",
                "施工照片只验证文件存在性与可读性，不执行OCR。",
                "本包不含金标，仅用于业务完整性测试。",
                "过程包含异常，S02、S03、S06最终均为合格闭环。",
            ],
        )
    elif spec.logical_id == "M00-MASTER-001":
        content["workbook"]["sheets"] = _all_master_sheets(master)
    elif spec.logical_id == "M00-STD-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "标准台账",
                ["标准号", "名称", "适用内容", "查新状态", "实施日期", "适用分册", "官方或项目来源"],
                STANDARDS,
            )
        ]
        _add_terms(content, "3 版本控制原则", [row[0] + "：" + row[3] for row in STANDARDS])
    elif spec.logical_id == "M00-DIR-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "资料总目录",
                ["逻辑编号", "分册", "文件名称", "源格式", "提交格式", "文件编号"],
                [
                    [
                        row["logicalId"],
                        row["folder"],
                        row["title"],
                        row["sourceFormat"].upper(),
                        row["submitFormat"].upper(),
                        row["documentNumber"],
                    ]
                    for row in catalog_rows
                ],
            ),
            _sheet(
                "覆盖统计",
                ["统计项", "数量", "结论"],
                [
                    ["逻辑资料", len(catalog_rows), "58，符合"],
                    [
                        "物理文件",
                        sum(2 if row["sourceFormat"] in {"docx", "xlsx"} else 1 for row in catalog_rows),
                        "114，符合",
                    ],
                    ["资料要求", len(requirement_rows), "166，符合"],
                ],
            ),
        ]


def _customize_b00(content: dict[str, Any], spec: DocumentSpec,
                   master: dict[str, Any]) -> None:
    base_facts = [
        "施工图 QX201903S-13-Y-07、QX201903S-13-Y-10，2021年3月，第2版。",
        "管道级别GC2，介质相关基础管线采用20#、Φ108×4。",
        "设计压力0.55 MPa；液压试验压力0.825 MPa；泄漏试验压力0.55 MPa。",
    ]
    _add_terms(content, "3 基础项目控制参数", base_facts)
    if spec.logical_id == "B00-DESIGN-001":
        content["tables"].append(
            _table(
                "设计输入核对表",
                ["输入项", "既有来源", "确认值", "状态"],
                [
                    ["项目名称", "施工图标题栏", PROJECT_NAME, "一致"],
                    ["图号", "管道平面图／轴测图", "QX201903S-13-Y-07、-10", "一致"],
                    ["管道级别", "设计说明", "GC2", "一致"],
                    ["材料规格", "材料表", "20#／Φ108×4", "一致"],
                    ["压力", "设计说明", "0.55 MPa／0.825 MPa", "一致"],
                ],
            )
        )
    elif spec.logical_id == "B00-CONSTRUCTION-001":
        _add_terms(
            content,
            "4 施工顺序与控制点",
            ["技术交底", "材料验收", "预制与标志移植", "焊接与NDT", "安装检查", "压力／泄漏试验", "吹扫清洗", "资料移交"],
        )
    elif spec.logical_id == "B00-QUALITY-001":
        content["tables"].append(
            _table(
                "质量控制点",
                ["控制点", "级别", "责任角色", "放行条件"],
                [
                    ["设计交底", "H", "设计／施工／建设", "问题清零"],
                    ["材料验收", "W", "材料责任人", "证明与实物一致"],
                    ["焊接/NDT", "H", "焊接／检测责任人", "报告合格"],
                    ["压力试验", "H", "质量责任人", "方案批准、仪表有效"],
                ],
            )
        )
    elif spec.logical_id == "B00-QUAL-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "单位",
                ["单位编号", "单位名称", "角色", "属性", "资料结论"],
                [
                    [row["id"], row["name"], row["role"], "合成" if row["synthetic"] else "来源复用", "已核对"]
                    for row in master["organizations"]
                ],
            ),
            _sheet(
                "人员证书",
                ["人员编号", "姓名", "岗位", "证书编号", "资料类型", "结论"],
                [
                    [
                        person["id"],
                        person["name"],
                        person["role"],
                        next(
                            (
                                cert["id"]
                                for cert in master["certificates"]
                                if cert["holder_id"] == person["id"]
                            ),
                            "TEST-ROLE-RECORD",
                        ),
                        "测试资质数据页",
                        "有效（测试）",
                    ]
                    for person in master["people"]
                ],
            ),
        ]
    elif spec.logical_id == "B00-LINES-001":
        content["workbook"]["sheets"] = [_all_master_sheets(master)[1]]
    elif spec.logical_id == "B00-MATERIAL-001":
        base_material = [row for row in master["materialBatches"] if row["id"] == "MAT-B00-20-001"]
        content["workbook"]["sheets"] = [
            _sheet(
                "验收台账",
                ["批次号", "牌号", "标准", "炉批号", "外观", "尺寸", "证明", "结论"],
                [
                    [row["id"], row["grade"], row["standard"], row["heatNumber"], "合格", "Φ108×4合格", "测试证明可追溯", "合格"]
                    for row in base_material
                ],
            )
        ]
    elif spec.logical_id == "B00-VALVE-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "阀门试验",
                ["阀门编号", "规格", "壳体压力MPa", "密封压力MPa", "保压min", "结果"],
                [
                    ["V-8301-TEST", "DN100 PN16", 2.4, 1.76, 5, "合格"],
                    ["V-8302-TEST", "DN50 PN16", 2.4, 1.76, 5, "合格"],
                ],
            )
        ]
    elif spec.logical_id == "B00-WELD-001":
        content["tables"].append(
            _table(
                "工艺评定与WPS",
                ["编号", "母材", "焊材", "焊接方法", "适用范围", "状态"],
                [
                    ["PQR-TEST-B00-01", "20#", "J427", "SMAW", "Φ60—Φ219／t3—12", "合格"],
                    ["WPS-TEST-B00-01", "20#", "J427", "SMAW", "B00基础管线", "批准"],
                ],
            )
        )
    elif spec.logical_id == "B00-WELD-LEDGER-001":
        rows = [row for row in master["welds"] if row["scenario"] == "B00"]
        content["workbook"]["sheets"] = [
            _sheet(
                "焊口台账",
                ["焊口号", "管线号", "材料批次", "完成日期", "焊工", "WPS", "NDT", "结果"],
                [
                    [row["id"], row["lineId"], row["materialBatchId"], row["completedOn"], "TEST-PER-WELD-01", "WPS-TEST-B00-01", "RT抽检", "合格"]
                    for row in rows
                ],
            )
        ]
    elif spec.logical_id == "B00-NDT-001":
        content["tables"].append(
            _table(
                "无损检测汇总",
                ["报告号", "对象", "方法", "比例", "级别", "结果"],
                [
                    ["TEST-NDT-B00-RT-001", "W-B00-001—012", "RT", "按设计抽检", "Ⅱ级", "合格"],
                    ["TEST-NDT-B00-PT-001", "支管角焊缝", "PT", "100%", "Ⅰ级", "合格"],
                ],
            )
        )
    elif spec.logical_id == "B00-TEST-001":
        _add_terms(
            content,
            "4 试验参数与安全措施",
            [
                "液压试验介质：洁净水；试验压力0.825 MPa；稳压10 min后降至设计压力检查。",
                "泄漏试验压力0.55 MPa；检漏介质空气；法兰、阀门填料和焊缝无泄漏。",
                "压力表量程0—1.6 MPa，两块，精度1.6级，均在TEST校准有效期。",
                "划定警戒区，升压分级，异常时先卸压后处理。",
            ],
        )
    elif spec.logical_id == "B00-INSTALL-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "安装检查",
                ["记录号", "工序", "管线", "检查内容", "日期", "结果"],
                [
                    ["TEST-B00-INST-01", "组对", "PL8301—PL8306", "错边、间隙、坡口", "2026-05-18", "合格"],
                    ["TEST-B00-INST-02", "支吊架", "PL8301—VT8302", "位置、型式、固定", "2026-05-19", "合格"],
                    ["TEST-B00-HYD-01", "液压试验", "B00基础管线", "0.825 MPa／10 min", "2026-05-20", "合格"],
                    ["TEST-B00-LEAK-01", "泄漏试验", "B00基础管线", "0.55 MPa／30 min", "2026-05-20", "合格"],
                    ["TEST-B00-PURGE-01", "吹扫", "B00基础管线", "白布靶板无可见杂物", "2026-05-20", "合格"],
                ],
            )
        ]


def _customize_s01(content: dict[str, Any], spec: DocumentSpec,
                   master: dict[str, Any]) -> None:
    chain = ["境外制造清单", "企业标准", "验证性复验", "技术评审", "型式试验", "标志移植"]
    _add_terms(content, "3 S01完整链", chain)
    _add_terms(
        content,
        "4 对象参数",
        [
            "管段PL8307-TEST；境外材料ASTM A312 TP316L；炉批TEST-HEAT-S01-F001。",
            "新材料TEST-NM01；企业标准TEST-QX-NM01-2026；炉批TEST-HEAT-S01-N001。",
            "境外制造商TEST-OVERSEAS-MFG-01；所有资质页均明确为测试资质数据页。",
        ],
    )
    if spec.source_format == "xlsx":
        if spec.logical_id == "S01-RETEST-001":
            content["workbook"]["sheets"] = [
                _sheet(
                    "复验结果",
                    ["批次", "试验项目", "要求", "结果", "结论", "报告号"],
                    [
                        ["MAT-S01-TP316L-001", "化学成分", "ASTM A312/A312M", "符合", "合格", "TEST-LAB-S01-001"],
                        ["MAT-S01-NM01-001", "拉伸", "Rm≥520 MPa", "548 MPa", "合格", "TEST-LAB-S01-002"],
                        ["MAT-S01-NM01-001", "晶间腐蚀", "无裂纹", "无裂纹", "合格", "TEST-LAB-S01-003"],
                        ["MAT-S01-NM01-001", "型式试验", "企业标准条款7", "符合", "合格", "TEST-TYPE-S01-001"],
                    ],
                )
            ]
        elif spec.logical_id == "S01-ACCEPT-001":
            content["workbook"]["sheets"] = [
                _sheet(
                    "到货验收",
                    ["批次", "标志", "证明", "规格", "PMI", "隔离状态", "结论"],
                    [
                        ["MAT-S01-TP316L-001", "清晰", "翻译件对应", "Φ108×4", "符合316L", "解除", "合格"],
                        ["MAT-S01-NM01-001", "清晰", "企业标准证明", "Φ108×4", "符合TEST-NM01", "解除", "合格"],
                    ],
                )
            ]
        elif spec.logical_id == "S01-MARK-001":
            content["workbook"]["sheets"] = [
                _sheet(
                    "标志移植",
                    ["切割件号", "原批次", "新标志", "移植人", "复核人", "结果"],
                    [
                        ["PL8307-TEST-P01", "MAT-S01-TP316L-001", "F001-P01", "测试焊工甲", "测试质量责任人员丁", "合格"],
                        ["PL8307-TEST-P02", "MAT-S01-NM01-001", "N001-P02", "测试焊工甲", "测试质量责任人员丁", "合格"],
                    ],
                )
            ]


def _customize_s02(content: dict[str, Any], spec: DocumentSpec) -> None:
    chain = ["代用申请", "技术比较", "强度校核", "设计批准", "材料采购", "安装合格", "合格闭环"]
    _add_terms(content, "3 S02代用闭环", chain)
    _add_terms(
        content,
        "4 代用参数",
        [
            "隔离对象：PL8303测试段，不改变其他基础管段。",
            "原材料20# Φ108×4，代用材料S30408 Φ108×4.5，批次MAT-S02-S30408-001。",
            "代用焊接工艺WPS-TEST-S02-01；强度、腐蚀裕量和连接兼容性校核满足。",
            "设计批准日期2026-06-05，采购日期2026-06-06，安装日期2026-06-09。",
        ],
    )
    if spec.logical_id == "S02-CALC-001":
        content["tables"].append(
            _table(
                "强度校核摘要",
                ["项目", "20#原设计", "S30408代用", "判定"],
                [
                    ["外径×壁厚", "Φ108×4", "Φ108×4.5", "壁厚增加"],
                    ["设计压力", "0.55 MPa", "0.55 MPa", "不变"],
                    ["许用应力取值", "按20#适用温度", "按S30408适用温度", "满足"],
                    ["计算厚度", "≤名义厚度-负偏差", "≤名义厚度-负偏差", "合格"],
                ],
            )
        )
    if spec.source_format == "xlsx":
        content["workbook"]["sheets"] = [
            _sheet(
                "验收安装",
                ["日期", "事件", "对象", "依据", "结果"],
                [
                    ["2026-06-05", "设计批准", "PL8303测试段", "QX201903S-13-Y-TEST-S02-001", "批准"],
                    ["2026-06-06", "材料采购", "MAT-S02-S30408-001", "代用批准书", "放行"],
                    ["2026-06-08", "到货验收", "S30408 Φ108×4.5", "材证／PMI", "合格"],
                    ["2026-06-09", "安装合格", "W-S02-001—003", "WPS-TEST-S02-01", "合格闭环"],
                ],
            )
        ]


def _s03_events() -> list[dict[str, Any]]:
    statuses = [
        ("2026-06-13T09:00", "施焊完成"),
        ("2026-06-14T10:30", "首次RT不合格"),
        ("2026-06-14T14:00", "返修批准"),
        ("2026-06-15T11:20", "返修完成"),
        ("2026-06-15T16:40", "RT复检合格"),
        ("2026-06-16T15:00", "焊后热处理完成"),
        ("2026-06-17T10:00", "硬度合格"),
    ]
    return [{"object": "W-S03-003", "date": date, "status": status} for date, status in statuses]


def _pwht_curve() -> list[dict[str, Any]]:
    values = [
        200, 350, 500, 640,
        672, 681, 686, 682, 679, 675, 670, 675, 671, 676, 681, 678, 670,
        655, 520, 380, 220,
    ]
    return [
        {
            "weld": "W-S03-003",
            "minute": index * 5,
            "tc1": value,
            "tc2": value - (3 if index % 2 else 1),
        }
        for index, value in enumerate(values)
    ]


def _customize_s03(content: dict[str, Any], spec: DocumentSpec,
                   master: dict[str, Any]) -> None:
    _add_terms(
        content,
        "3 工艺与闭环要求",
        [
            "ST8301-TEST，15CrMoG，Φ76×16，设计压力2.5 MPa，设计温度300 ℃。",
            "PWHT 680±20 ℃，保温60 min；两支热电偶；记录仪TEST-HTR-001。",
            "W-S03-003首次RT发现未熔合，返修批准后完成首次返修，复检合格后再进行PWHT。",
            "测试模拟底片图，不得作为真实检测底片。",
        ],
    )
    weld_rows = [
        row for row in master["welds"] if row["scenario"] == "S03"
    ]
    if spec.logical_id == "S03-WELDER-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "焊工焊材",
                ["焊工", "资格编号", "WPS", "焊材", "烘干", "领用", "结论"],
                [["测试焊工甲", "TEST-CERT-WELDER-001", "WPS-TEST-S03-01", "R307", "350℃×1h", "可追溯", "合格"]],
            )
        ]
    elif spec.logical_id == "S03-WELDLOG-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "施焊台账",
                ["焊口号", "完成日期", "WPS", "焊工", "首次RT", "返修次数", "最终状态"],
                [
                    [row["id"], row["completedOn"], "WPS-TEST-S03-01", "TEST-PER-WELD-01", "不合格" if row["id"] == "W-S03-003" else "合格", row.get("repairCount", 0), "合格闭环"]
                    for row in weld_rows
                ],
            ),
            _sheet(
                "异常时间线",
                ["对象", "日期时间", "状态"],
                [[row["object"], row["date"], row["status"]] for row in _s03_events()],
            ),
        ]
    elif spec.logical_id == "S03-NDT-INITIAL-001":
        content["evidence_panels"] = [
            {
                "label": "测试模拟底片图，不得作为真实检测底片",
                "object": "W-S03-003",
                "annotation": "2点钟方向／距基准42 mm／模拟未熔合6 mm",
                "pattern": "█▓▒░  ──  ░▒▓██▓▒░  ▲  ░▒▓█  ──  ░▒▓█",
            }
        ]
        content["tables"].append(
            _table(
                "首次RT结果",
                ["报告号", "焊口", "位置", "缺陷", "判级", "结论"],
                [["TEST-RT-S03-001", "W-S03-003", "2点钟／距基准42 mm", "未熔合6 mm", "超标", "不合格"]],
            )
        )
    elif spec.logical_id == "S03-REPAIR-001":
        content["tables"].append(
            _table(
                "返修卡",
                ["返修卡号", "焊口", "次数", "缺陷清除", "工艺", "检查", "状态"],
                [["TEST-REPAIR-S03-001", "W-S03-003", "第1次", "打磨至缺陷清除并PT确认", "WPS-TEST-S03-R01", "外观合格", "返修完成"]],
            )
        )
    elif spec.logical_id == "S03-NDT-REPEAT-001":
        content["tables"].append(
            _table(
                "复检结果",
                ["报告号", "焊口", "方法", "范围", "结果", "结论"],
                [["TEST-RT-S03-002", "W-S03-003", "RT", "原缺陷部位及两端延伸", "未见超标缺陷", "合格闭环"]],
            )
        )
    elif spec.logical_id == "S03-PWHT-001":
        content["tables"].append(
            _table(
                "热处理工艺与仪表",
                ["项目", "要求／信息", "状态"],
                [
                    ["升降温", "按批准曲线控制", "受控"],
                    ["保温温度", "680±20 ℃", "符合"],
                    ["保温时间", "60 min", "符合"],
                    ["记录仪", "TEST-HTR-001／有效至2026-12-31", "有效"],
                    ["热电偶", "TC-TEST-01、TC-TEST-02", "有效"],
                ],
            )
        )
    elif spec.logical_id == "S03-PWHT-RECORD-001":
        curve = _pwht_curve()
        hardness_rows = [
            [weld, point, value, "≤225 HB", "合格"]
            for weld, values in {
                "W-S03-001": [198, 203, 201],
                "W-S03-002": [205, 207, 204],
                "W-S03-003": [211, 214, 209],
                "W-S03-004": [202, 206, 203],
            }.items()
            for point, value in enumerate(values, start=1)
        ]
        content["workbook"]["sheets"] = [
            _sheet(
                "热处理曲线",
                ["焊口", "分钟", "TC1℃", "TC2℃"],
                [[row["weld"], row["minute"], row["tc1"], row["tc2"]] for row in curve],
            ),
            _sheet(
                "硬度记录",
                ["焊口", "测点", "硬度HB", "要求", "结论"],
                hardness_rows,
            ),
        ]


def _customize_s04(content: dict[str, Any], spec: DocumentSpec) -> None:
    _add_terms(
        content,
        "3 设计与施工参数",
        [
            "PL8308-TEST道路穿越长度18 m；载管20# Φ108×4；套管Φ273×7。",
            "两支11 kg镁阳极、测试桩TEST-TP-001、排流连接TEST-DR-001。",
            "自然电位与通电电位均使用铜/硫酸铜参比电极；合格范围-0.85至-1.20 V CSE。",
            "照片附件只按存在性与可读性提交，不执行OCR。",
        ],
    )
    if spec.logical_id == "S04-EQUIP-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "设备材料",
                ["编号", "名称", "规格", "数量", "证明", "验收"],
                [
                    ["TEST-CP-MG-01", "镁合金牺牲阳极", "11 kg", 2, "TEST-MTC-CP-001", "合格"],
                    ["TEST-TP-001", "阴保测试桩", "6端子", 1, "TEST-MTC-CP-002", "合格"],
                    ["TEST-CASING-001", "钢制套管", "Φ273×7", "18 m", "TEST-MTC-CP-003", "合格"],
                ],
            )
        ]
    elif spec.logical_id == "S04-INSTALL-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "穿越安装",
                ["工序", "记录", "实测", "要求", "结论"],
                [
                    ["沟槽", "标高／坡度", "符合设计", "QX201903S-13-Y-TEST-S04-001", "合格"],
                    ["套管", "长度", "18.0 m", "18 m", "合格"],
                    ["绝缘支撑", "间距", "2.0 m", "≤2.0 m", "合格"],
                    ["焊缝位置", "W-S04-001—003", "未置于套管封闭段不可检位置", "可检", "合格"],
                    ["回填", "细土保护", "完成", "无硬物损伤", "合格"],
                ],
            )
        ]
    elif spec.logical_id == "S04-CP-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "阴保调试",
                ["测点", "自然电位V", "通电电位V CSE", "目标范围V", "极性", "结论"],
                [
                    ["TP-01", -0.71, -0.93, "-0.85~-1.20", "正确", "合格"],
                    ["TP-02", -0.74, -1.02, "-0.85~-1.20", "正确", "合格"],
                    ["TP-03", -0.69, -0.89, "-0.85~-1.20", "正确", "合格"],
                ],
            )
        ]


def _customize_s05(content: dict[str, Any], spec: DocumentSpec) -> None:
    _add_terms(
        content,
        "3 安全附件对象",
        [
            "PSV-8301-TEST：DN50 PN16，整定压力0.50 MPa。",
            "RD-8301-TEST：DN50，20 ℃标定爆破压力0.52 MPa。",
            "ESDV-8301-TEST：DN100 PN16，关闭时间不大于2 s。",
            "产品质量证明、型式资料、到货、安装、校验／性能记录逐台追溯。",
        ],
    )
    if spec.logical_id == "S05-ACCESSORY-001":
        content["tables"].append(
            _table(
                "产品资料索引",
                ["设备位号", "产品编号", "质量证明", "型式资料", "结论"],
                [
                    ["PSV-8301-TEST", "TEST-SN-PSV-001", "TEST-MTC-PSV-001", "测试资质数据页", "合格"],
                    ["RD-8301-TEST", "TEST-SN-RD-001", "TEST-MTC-RD-001", "测试资质数据页", "合格"],
                    ["ESDV-8301-TEST", "TEST-SN-ESDV-001", "TEST-MTC-ESDV-001", "测试资质数据页", "合格"],
                ],
            )
        )
    elif spec.logical_id == "S05-PSV-001":
        content["tables"].append(
            _table(
                "安全阀校验",
                ["位号", "整定压力MPa", "回座压力MPa", "密封", "仪表", "结果"],
                [["PSV-8301-TEST", 0.50, 0.46, "无可见泄漏", "TEST-PG-PSV-001／有效", "合格"]],
            )
        )
    elif spec.source_format == "xlsx":
        if spec.logical_id == "S05-INSTALL-001":
            content["workbook"]["sheets"] = [
                _sheet(
                    "到货安装",
                    ["设备位号", "序列号", "铅封／标志", "安装方向", "连接", "结果"],
                    [
                        ["PSV-8301-TEST", "TEST-SN-PSV-001", "完好（测试）", "正确", "合格", "合格"],
                        ["RD-8301-TEST", "TEST-SN-RD-001", "完好（测试）", "正确", "合格", "合格"],
                        ["ESDV-8301-TEST", "TEST-SN-ESDV-001", "完好（测试）", "正确", "合格", "合格"],
                    ],
                )
            ]
        elif spec.logical_id == "S05-ESDV-001":
            content["workbook"]["sheets"] = [
                _sheet(
                    "性能记录",
                    ["设备位号", "试验项目", "设定／要求", "实测", "仪表", "结论"],
                    [
                        ["RD-8301-TEST", "爆破压力", "0.52 MPa@20℃", "0.518 MPa@20℃", "TEST-PG-RD-001", "合格"],
                        ["ESDV-8301-TEST", "关闭时间", "≤2 s", "1.6 s", "TEST-TIMER-001", "合格"],
                        ["ESDV-8301-TEST", "联锁动作", "失电关闭", "动作正确", "TEST-DCS-POINT-01", "合格"],
                    ],
                )
            ]


def _customize_s06(content: dict[str, Any], spec: DocumentSpec,
                   master: dict[str, Any]) -> None:
    _add_terms(
        content,
        "3 替代检验闭环",
        [
            "对象仅为PL8306最终封闭段，不引用B00液压试验报告作为本段验收证据。",
            "因已连接在役边界且无法安全隔离充水，提出耐压替代；施工、设计、建设、监检角色于焊前批准。",
            "W-S06-001—003执行100% RT和100% MT；模拟底片仅作测试证据面板。",
            "最终执行0.55 MPa、30 min泄漏试验，无压降、无泄漏，状态合格闭环。",
        ],
    )
    if spec.logical_id == "S06-ANALYSIS-001":
        content["tables"].append(
            _table(
                "应力与风险校核",
                ["工况", "计算值", "许用／判据", "结论"],
                [
                    ["设计压力0.55 MPa", "一次薄膜应力22 MPa", "≤许用应力", "合格"],
                    ["热位移", "等效应力范围41 MPa", "≤许用范围", "合格"],
                    ["替代风险", "泄漏／缺陷残留", "100%RT+100%MT+泄漏试验", "可控"],
                ],
            )
        )
    elif spec.logical_id == "S06-APPROVAL-001":
        content["tables"].append(
            _table(
                "批准顺序",
                ["日期", "角色", "单位／人员", "意见", "记录"],
                [
                    ["2026-07-01", "施工", "TEST-压力管道安装单位／测试质量责任人员丁", "同意申请", "电子记录（测试）"],
                    ["2026-07-02", "设计", "广东星燃石化设计院有限公司／测试设计负责人甲", "技术同意", "电子记录（测试）"],
                    ["2026-07-02", "建设", "珠海恒基达鑫国际化工仓储股份有限公司／TEST-建设代表", "同意实施", "电子记录（测试）"],
                    ["2026-07-03", "监检角色", "TEST-监督检验角色单位／TEST-监检人员", "方案确认", "电子记录（测试）"],
                ],
            )
        )
    elif spec.logical_id == "S06-NDT-001":
        content["evidence_panels"] = [
            {
                "label": "测试模拟底片图，不得作为真实检测底片",
                "object": weld,
                "annotation": "100% RT模拟影像面板／未见超标缺陷",
                "pattern": "█▓▒░  ───────  ░▒▓██▓▒░  ───────  ░▒▓█",
            }
            for weld in ["W-S06-001", "W-S06-002", "W-S06-003"]
        ]
        content["tables"].append(
            _table(
                "100%检测结果",
                ["焊口", "RT覆盖", "RT结论", "MT覆盖", "MT结论", "底片标识"],
                [
                    [weld, "100%", "Ⅱ级合格", "100%", "合格", f"TEST-FILM-{index:03d}"]
                    for index, weld in enumerate(
                        ["W-S06-001", "W-S06-002", "W-S06-003"], start=1
                    )
                ],
            )
        )
    elif spec.logical_id == "S06-FINAL-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "替代检测",
                ["焊口", "RT覆盖%", "RT结论", "MT覆盖%", "MT结论", "证据编号"],
                [
                    [weld, 100, "合格", 100, "合格", f"TEST-S06-NDT-{index:03d}"]
                    for index, weld in enumerate(
                        ["W-S06-001", "W-S06-002", "W-S06-003"], start=1
                    )
                ],
            ),
            _sheet(
                "泄漏试验",
                ["对象", "压力MPa", "保压min", "起压MPa", "终压MPa", "泄漏", "最终状态"],
                [["PL8306最终封闭段", 0.55, 30, 0.55, 0.55, "无", "合格闭环"]],
            ),
        ]


def _customize_v00(content: dict[str, Any], spec: DocumentSpec,
                   master: dict[str, Any], catalog_rows: list[dict[str, Any]],
                   requirement_rows: list[dict[str, Any]]) -> None:
    if spec.logical_id == "V00-NODE-MATRIX-001":
        rows = []
        for node in range(1, 70):
            docs = [
                row["logicalId"] for row in catalog_rows if node in row["rNodes"]
            ]
            rows.append(
                [
                    f"R{node:02d}",
                    "工作流节点" if node == 69 else "资料节点",
                    "、".join(docs) if docs else "无外部文件绑定",
                    "已覆盖",
                ]
            )
        content["workbook"]["sheets"] = [
            _sheet("节点矩阵", ["节点", "类型", "逻辑资料", "状态"], rows)
        ]
    elif spec.logical_id == "V00-REQ-MATRIX-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "166项要求",
                ["要求编号", "节点", "要求名称", "状态", "逻辑资料", "定位／理由"],
                [
                    [
                        row["requirementId"],
                        f"R{int(row['node']):02d}",
                        row["materialName"],
                        row["status"],
                        row["logicalDocumentId"],
                        row.get("locator") or row.get("rationale", ""),
                    ]
                    for row in requirement_rows
                ],
            )
        ]
    elif spec.logical_id == "V00-SOURCE-DIFF-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "来源差异",
                ["数据项", "来源／设置", "使用方式", "差异控制"],
                [
                    ["项目名称", "既有施工图", "原样复用", "无差异"],
                    ["设计单位", "既有施工图", "原样复用", "无差异"],
                    ["图号", "QX201903S-13-Y-07、-10", "基础事实", "无差异"],
                    ["原设计参数", "20#／Φ108×4／0.55 MPa", "B00保持", "无差异"],
                    ["新增单位人员", "TEST前缀", "测试身份", "不得用于真实工程"],
                    ["S01—S06", "测试专用设计变更", "独立场景", "不污染基础资料"],
                    ["施工照片", "占位附件", "存在性／可读性", "未执行OCR"],
                ],
            )
        ]
    elif spec.logical_id == "V00-CHECKSUM-001":
        content["workbook"]["sheets"] = [
            _sheet(
                "文件校验",
                ["序号", "逻辑编号", "预期文件", "格式", "SHA-256", "校验状态"],
                [
                    [
                        index,
                        row["logicalId"],
                        row["fileStem"],
                        row["sourceFormat"].upper() + ("/PDF" if row["sourceFormat"] in {"docx", "xlsx"} else ""),
                        "构建后由验证器填充",
                        "待构建校验",
                    ]
                    for index, row in enumerate(catalog_rows, start=1)
                ],
            )
        ]
    elif spec.logical_id == "V00-REPORT-001":
        _add_terms(
            content,
            "3 完整性指标",
            [
                "R01—R69节点：69个；R01—R68均有业务资料；R69为工作流节点。",
                f"资料要求：{len(requirement_rows)}项；均有状态和定位／适用性说明。",
                f"逻辑资料：{len(catalog_rows)}份；物理文件：114个。",
                f"对象主数据：管线{len(master['lines'])}条、焊口{len(master['welds'])}道、主要材料{len(master['materialBatches'])}批。",
            ],
        )
        content["sections"][-1]["paragraphs"] = [
            "业务资料齐全，R01–R69测试场景全部覆盖；",
            "过程异常均已闭环，最终状态合格；",
            "施工照片按存在性附件提交，未执行OCR。",
            TEST_WARNING,
        ]


def build_content_payloads(
    master: dict[str, Any],
    catalog_payload: dict[str, Any],
    requirement_payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    catalog_path = Path(__file__).parent / "data/document_catalog.json"
    catalog = load_catalog(catalog_path)
    catalog_rows = catalog_payload["documents"]
    requirement_rows = requirement_payload["requirements"]
    grouped: dict[str, dict[str, Any]] = {}
    for spec in catalog.documents:
        content = _base_content(spec)
        if spec.folder == "M00":
            _customize_m00(content, spec, master, catalog_rows, requirement_rows)
        elif spec.folder == "B00":
            _customize_b00(content, spec, master)
        elif spec.folder == "S01":
            _customize_s01(content, spec, master)
        elif spec.folder == "S02":
            _customize_s02(content, spec)
        elif spec.folder == "S03":
            _customize_s03(content, spec, master)
        elif spec.folder == "S04":
            _customize_s04(content, spec)
        elif spec.folder == "S05":
            _customize_s05(content, spec)
        elif spec.folder == "S06":
            _customize_s06(content, spec, master)
        elif spec.folder == "V00":
            _customize_v00(
                content, spec, master, catalog_rows, requirement_rows
            )
        grouped.setdefault(
            spec.folder,
            {
                "schemaVersion": "r01-r69-content@1",
                "scenario": spec.folder,
                "scenarioData": {},
                "documents": {},
            },
        )["documents"][spec.logical_id] = content

    grouped["S02"]["scenarioData"] = {
        "events": [
            {"date": "2026-06-05", "status": "设计批准"},
            {"date": "2026-06-06", "status": "材料采购"},
            {"date": "2026-06-09", "status": "安装合格"},
            {"date": "2026-06-10", "status": "合格闭环"},
        ]
    }
    grouped["S03"]["scenarioData"] = {
        "events": _s03_events(),
        "pwhtCurve": _pwht_curve(),
        "hardness": {
            "W-S03-001": [198, 203, 201],
            "W-S03-002": [205, 207, 204],
            "W-S03-003": [211, 214, 209],
            "W-S03-004": [202, 206, 203],
        },
    }
    grouped["S04"]["scenarioData"] = {
        "photoOcrRequired": False,
        "cpPotentials": [-0.93, -1.02, -0.89],
    }
    grouped["S05"]["scenarioData"] = {
        "accessories": [
            {"id": "PSV-8301-TEST", "result": "合格"},
            {"id": "RD-8301-TEST", "result": "合格"},
            {"id": "ESDV-8301-TEST", "result": "合格"},
        ]
    }
    grouped["S06"]["scenarioData"] = {
        "acceptanceEvidenceIds": [
            "S06-APPROVAL-001",
            "S06-NDT-001",
            "S06-FINAL-001",
        ],
        "coverage": {
            weld: {"rt": 100, "mt": 100}
            for weld in ["W-S06-001", "W-S06-002", "W-S06-003"]
        },
        "leakTest": {"pressure_mpa": 0.55, "minutes": 30},
        "finalStatus": "合格闭环",
    }
    return grouped


def write_content_files(data_dir: Path) -> None:
    master = json.loads((data_dir / "project_master.json").read_text(encoding="utf-8"))
    catalog = json.loads((data_dir / "document_catalog.json").read_text(encoding="utf-8"))
    requirements = json.loads((data_dir / "requirement_map.json").read_text(encoding="utf-8"))
    output_dir = data_dir / "content"
    output_dir.mkdir(parents=True, exist_ok=True)
    for folder, payload in build_content_payloads(master, catalog, requirements).items():
        (output_dir / f"{folder}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def load_content_library(content_dir: Path) -> dict[str, dict[str, Any]]:
    library: dict[str, dict[str, Any]] = {}
    for path in sorted(content_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        library.update(payload["documents"])
    return library


def load_scenario_data(content_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8")).get(
            "scenarioData", {}
        )
        for path in sorted(content_dir.glob("*.json"))
    }


def main() -> int:
    data_dir = Path(__file__).parent / "data"
    write_content_files(data_dir)
    library = load_content_library(data_dir / "content")
    print(f"content_documents={len(library)} output={data_dir / 'content'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
