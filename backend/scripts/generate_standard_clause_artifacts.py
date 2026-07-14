#!/usr/bin/env python3
"""Generate the fixed clause packages for the 69 engineering inspection rules.

The curated maps in this file are deliberately explicit.  Business wording and
node metadata are read from rules.yaml, while standard/clause selection is never
inferred by an LLM at review-run time.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import yaml


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
PACK_DIR = BACKEND_ROOT / "business_packs" / "engineering_inspection_v1"
RULES_FILE = PACK_DIR / "rules.yaml"
DOCS_DIR = REPO_ROOT / "docs"


def catalog_item(
    id_: str,
    code: str,
    name: str,
    source_file: str,
    method: str = "source_pdf_text_and_visual_check",
    **extra: object,
) -> dict[str, object]:
    return {
        "id": id_,
        "code": code,
        "name": name,
        "sourceFile": source_file,
        "verificationMethod": method,
        **extra,
    }


CATALOG = [
    catalog_item("STD-TSG-D7006-2020", "TSG D7006—2020", "压力管道监督检验规则", "rules/standards/TSG D7006-2020 压力管道监督检验规则.pdf", "knowledge_base_raw_pdf_chunk_and_visual_check", knowledgeFileId="KF-KB-CE49677F5B", documentVersionId="KDV-CE49677F5B-V1"),
    catalog_item("STD-TSG-31-2025", "TSG 31—2025", "工业管道安全技术规程", "rules/standards/TSG31-2025.pdf", "source_pdf_visual_check"),
    catalog_item("STD-TSG-07-2019", "TSG 07—2019", "特种设备生产和充装单位许可规则", "rules/standards/特种设备生产和充装单位许可规则TSG 07-2019.pdf"),
    catalog_item("STD-SAMR-2021-41", "市场监管总局公告2021年第41号", "特种设备行政许可有关事项的公告", "rules/standards/市场监管总局关于特种设备行政许可有关事项的公告（2021年41号）.pdf", "source_pdf_visual_check"),
    catalog_item("STD-TSG-Z7002-2022", "TSG Z7002—2022", "特种设备检测机构核准规则", "rules/standards/TSG Z7002—2022.pdf", "source_pdf_visual_check"),
    catalog_item("STD-TSG-Z6002-2010", "TSG Z6002—2010", "特种设备焊接操作人员考核细则", "rules/standards/TSGZ6002-2010《焊接人员考核细则》.pdf", "source_pdf_visual_check"),
    catalog_item("STD-GBT-20801.1-2025", "GB/T 20801.1—2025", "压力管道规范 工业管道", "rules/standards/GBT+20801.1-2025.pdf", "source_pdf_text_and_visual_check", knowledgeFileId="KF-KB-7ED59299DE", documentVersionId="KDV-7ED59299DE-V1"),
    catalog_item("STD-NBT-47014-2023", "NB/T 47014—2023", "承压设备焊接工艺评定", "rules/standards/NBT47014-2023《承压设备焊接工艺评定》.pdf"),
    catalog_item("STD-JBT-3223-2017", "JB/T 3223—2017", "焊接材料质量管理规程", "rules/standards/JB∕T 3223-2017 焊接材料质量管理规程.pdf"),
    catalog_item("STD-NBT-47013.1-2015", "NB/T 47013.1—2015", "承压设备无损检测 第1部分：通用要求", "rules/standards/NB_T_47013_split/NB_T 47013.1-2015 承压设备无损检测 第1部分 通用要求.pdf", "source_pdf_visual_check"),
    catalog_item("STD-NBT-47013.2-2015", "NB/T 47013.2—2015", "承压设备无损检测 第2部分：射线检测", "rules/standards/NB_T_47013_split/NB_T 47013.2-2015 承压设备无损检测 第2部分 射线检测.pdf", "source_pdf_visual_check"),
    catalog_item("STD-NBT-47013.3-2023", "NB/T 47013.3—2023", "承压设备无损检测 第3部分：超声检测", "rules/standards/NB_T_47013_split/NBT 47013.3-2023 承压设备无损检测 第3部分 超声检测.pdf"),
    catalog_item("STD-NBT-47013.11-2023", "NB/T 47013.11—2023", "承压设备无损检测 第11部分：射线数字成像检测", "rules/standards/NB_T_47013_split/NBT47013.11-2023 承压设备无损检测 第11部分：射线数字成像检测_可搜索.pdf"),
    catalog_item("STD-GBT-19285-2026", "GB/T 19285—2026", "埋地钢质管道腐蚀防护工程检验", "rules/standards/GBT+19285-2026埋地钢质管道腐蚀防护工程检验.pdf"),
    catalog_item("STD-GBT-33378-2025", "GB/T 33378—2025", "阴极保护技术条件", "rules/standards/GBT+33378-2025阴极保护技术条件.pdf"),
    catalog_item("STD-SYT-4113.11-2023", "SY/T 4113.11—2023", "管道防腐层性能试验方法 第11部分：漏点检测", "rules/standards/SYT 4113.11—2023 管道防腐层性能试验方法 第11部分：漏点检测.pdf", "source_pdf_visual_check"),
    catalog_item("STD-GBT-21448-2017", "GB/T 21448—2017", "埋地钢质管道阴极保护技术规范", "rules/standards/GB∕T 21448-2017 埋地钢质管道阴极保护技术规范.pdf"),
    catalog_item("STD-GB-50235-2010", "GB 50235—2010", "工业金属管道工程施工规范", "rules/standards/GB 50235-2010 工业金属管道工程施工规范.pdf", "source_pdf_visual_check"),
    catalog_item("STD-TSG-92-2026", "TSG 92—2026", "承压类特种设备安全附件安全技术规程", "rules/standards/TSG  92—2026《承压类特种设备安全附件安全技术规程》.pdf", "source_pdf_visual_check"),
    catalog_item("STD-GBT-13927-2022", "GB/T 13927—2022", "工业阀门 压力试验", "rules/standards/GB_T 13927-2022+工业阀门·压力试验.pdf"),
    catalog_item("STD-GBT-26480-2011", "GB/T 26480—2011", "阀门的检验和试验", "rules/standards/GBT 26480-2011 阀门的检验和试验.pdf"),
    catalog_item("STD-GBT-8163-2018", "GB/T 8163—2018", "输送流体用无缝钢管", "rules/standards/GBT 8163-2018 输送流体用无缝钢管.pdf"),
    catalog_item("STD-GBT-3087-2022", "GB/T 3087—2022", "低中压锅炉用无缝钢管", "rules/standards/GBT+3087-2022.pdf"),
    catalog_item("STD-GBT-5310-2023", "GB/T 5310—2023", "高压锅炉用无缝钢管", "rules/standards/GBT+5310-2023.pdf"),
    catalog_item("STD-GBT-9948-2025", "GB/T 9948—2025", "石油裂化用无缝钢管", "rules/standards/GBT+9948-2025石化和化工装置用无缝钢管.pdf"),
    catalog_item("STD-GBT-14976-2025", "GB/T 14976—2025", "流体输送用不锈钢无缝钢管", "rules/standards/GBT+14976-2025输送流体用不锈钢无缝钢管.pdf"),
    catalog_item("STD-GBT-12771-2019", "GB/T 12771—2019", "流体输送用不锈钢焊接钢管", "rules/standards/GB∕T 12771-2019 流体输送用不锈钢焊接钢管.pdf"),
    catalog_item("STD-GBT-12459-2025", "GB/T 12459—2025", "钢制对焊管件 类型与参数", "rules/standards/GBT 12459-2025 钢制对焊管件 类型与参数.pdf"),
    catalog_item("STD-GBT-13401-2025", "GB/T 13401—2025", "钢制对焊管件 技术规范", "rules/standards/GBT 13401-2025钢制对焊管件 技术规范.pdf"),
]


# These ids are the stable knowledge-base records for the source PDFs.  A page
# locator is only useful to the UI when it can also resolve the concrete file.
KNOWLEDGE_DOCUMENTS = {
    "STD-TSG-D7006-2020": ("KF-KB-CE49677F5B", "KDV-CE49677F5B-V1"),
    "STD-TSG-31-2025": ("KF-KB-E6E1201DF9", "KDV-E6E1201DF9-V1"),
    "STD-TSG-07-2019": ("KF-KB-0DD3FC7201", "KDV-0DD3FC7201-V1"),
    "STD-SAMR-2021-41": ("KF-KB-72C3E5B097", "KDV-72C3E5B097-V1"),
    "STD-TSG-Z7002-2022": ("KF-KB-CF3526F5AC", "KDV-CF3526F5AC-V1"),
    "STD-TSG-Z6002-2010": ("KF-KB-DE16B8E7E8", "KDV-DE16B8E7E8-V1"),
    "STD-GBT-20801.1-2025": ("KF-KB-7ED59299DE", "KDV-7ED59299DE-V1"),
    "STD-NBT-47014-2023": ("KF-KB-76FBE61C16", "KDV-76FBE61C16-V1"),
    "STD-JBT-3223-2017": ("KF-KB-BECBD1A8FE", "KDV-BECBD1A8FE-V1"),
    "STD-NBT-47013.1-2015": ("KF-KB-B0D5FBA01C", "KDV-B0D5FBA01C-V1"),
    "STD-NBT-47013.2-2015": ("KF-KB-A0592BD6C0", "KDV-A0592BD6C0-V1"),
    "STD-NBT-47013.3-2023": ("KF-KB-FD7D9CCF13", "KDV-FD7D9CCF13-V1"),
    "STD-NBT-47013.11-2023": ("KF-KB-755A3414FF", "KDV-755A3414FF-V1"),
    "STD-GBT-19285-2026": ("KF-KB-D27E9BF359", "KDV-D27E9BF359-V1"),
    "STD-GBT-33378-2025": ("KF-KB-091050A264", "KDV-091050A264-V1"),
    "STD-SYT-4113.11-2023": ("KF-KB-57EB2C0B90", "KDV-57EB2C0B90-V1"),
    "STD-GBT-21448-2017": ("KF-KB-9911A3A070", "KDV-9911A3A070-V1"),
    "STD-GB-50235-2010": ("KF-KB-0E11194CB6", "KDV-0E11194CB6-V1"),
    "STD-TSG-92-2026": ("KF-KB-7979D2C4C2", "KDV-7979D2C4C2-V1"),
    "STD-GBT-13927-2022": ("KF-KB-FC8054EEB2", "KDV-FC8054EEB2-V1"),
    "STD-GBT-26480-2011": ("KF-KB-B9AEEAD2BE", "KDV-B9AEEAD2BE-V1"),
    "STD-GBT-8163-2018": ("KF-KB-FC7BD2864D", "KDV-FC7BD2864D-V1"),
    "STD-GBT-3087-2022": ("KF-KB-A6A3DB4C53", "KDV-A6A3DB4C53-V1"),
    "STD-GBT-5310-2023": ("KF-KB-4D1CE27E27", "KDV-4D1CE27E27-V1"),
    "STD-GBT-9948-2025": ("KF-KB-DAB23C4B28", "KDV-DAB23C4B28-V1"),
    "STD-GBT-14976-2025": ("KF-KB-D30C53CE05", "KDV-D30C53CE05-V1"),
    "STD-GBT-12771-2019": ("KF-KB-EF422C04B1", "KDV-EF422C04B1-V1"),
    "STD-GBT-12459-2025": ("KF-KB-D027E2E0C4", "KDV-D027E2E0C4-V1"),
    "STD-GBT-13401-2025": ("KF-KB-3F0F9D88CD", "KDV-3F0F9D88CD-V1"),
}

for _standard in CATALOG:
    _standard["knowledgeFileId"], _standard["documentVersionId"] = KNOWLEDGE_DOCUMENTS[_standard["id"]]


def primary_map() -> dict[str, tuple[str, str, int]]:
    values: dict[str, tuple[str, str, int]] = {}
    for n in range(1, 4):
        values[f"R{n:02d}"] = ("STD-TSG-D7006-2020", "D2.1", 27)
    for n, item in zip(range(4, 10), range(1, 7), strict=True):
        values[f"R{n:02d}"] = ("STD-TSG-D7006-2020", f"D2.2({item})", 27)
    values["R10"] = ("STD-TSG-31-2025", "1.9(3)", 7)
    values["R11"] = ("STD-TSG-D7006-2020", "D2.3", 27)
    direct = {
        12: ("D2.4.1(1)", 27), 13: ("D2.4.1(2)", 28), 14: ("D2.4.1(3)", 28),
        15: ("D2.4.1(4)", 28), 16: ("D2.4.1(5)", 28), 17: ("D2.4.1(6)", 28),
        18: ("D2.4.1(7)", 28), 19: ("D2.4.1(8)", 28), 20: ("D2.4.1(9)", 28),
        21: ("D2.4.2", 28), 22: ("D2.4.3", 28), 23: ("D2.5", 28),
        24: ("D2.6.1", 28), 25: ("D2.6.2", 29), 26: ("D2.6.3(1)", 29),
        27: ("D2.6.3(2)", 29), 28: ("D2.6.4", 29), 29: ("D2.6.5(1)", 29),
        30: ("D2.6.5(2)", 29), 31: ("D2.6.6", 29), 32: ("D2.7(1)", 29),
        33: ("D2.7(2)", 29), 34: ("D2.7(3)", 29), 35: ("D2.8.1(1)", 29),
        36: ("D2.8.1(2)", 29), 37: ("D2.8.1(3)", 29), 38: ("D2.8.2", 29),
        39: ("D2.8.3", 30), 40: ("D2.8.4", 30), 41: ("D2.8.5", 30),
        42: ("D2.8.6", 30), 43: ("D2.9(1)", 30), 44: ("D2.9(2)", 30),
        45: ("D2.9(3)", 30), 46: ("D2.9(3)", 30), 47: ("D2.9(4)", 30),
        48: ("D2.10(1)", 30), 49: ("D2.10(2)", 31), 50: ("D2.10(3)", 31),
        51: ("D2.10(4)", 31), 52: ("D2.11(1)", 31), 53: ("D2.11(2)", 31),
        54: ("D2.11(2)", 31), 55: ("D2.11(2)", 31), 56: ("D2.12(1)", 31),
        57: ("D2.12(2)", 31), 58: ("D2.12(3)", 31), 59: ("D2.13.1(1)", 31),
        60: ("D2.13.1(2)", 31), 61: ("D2.13.1(3)", 31), 62: ("D2.13.1(4)", 31),
        63: ("D2.13.2(1)", 31), 64: ("D2.13.2(2)", 31), 65: ("D2.13.2(3)", 31),
        66: ("D2.14(1)", 32), 67: ("D2.14(2)", 32), 68: ("D2.15", 32),
        69: ("2.2.4", 9),
    }
    for n, (clause, page) in direct.items():
        values[f"R{n:02d}"] = ("STD-TSG-D7006-2020", clause, page)
    return values


def c(ref: str, clause: str, purpose: str, applicability: str = "always", status: str = "source_verified") -> dict[str, str]:
    return {"standardRef": ref, "clauseNo": clause, "purpose": purpose, "applicability": applicability, "verificationStatus": status}


SUPPLEMENTAL: dict[str, list[dict[str, str]]] = {
    "R01": [c("STD-TSG-31-2025", "3.1.1-3.1.2", "设计单位许可及设计许可印章"), c("STD-TSG-07-2019", "E1.1、E1.2.2", "许可基本条件和人员条件"), c("STD-SAMR-2021-41", "附件1：特种设备生产单位许可目录", "现行许可级别和范围", status="visual_verified")],
    "R02": [c("STD-TSG-07-2019", "E3.1、E3.2.5-E3.2.7、表E-13-E-14", "工业管道安装许可及资源条件"), c("STD-SAMR-2021-41", "附件1：特种设备生产单位许可目录", "现行安装许可范围", status="visual_verified")],
    "R03": [c("STD-TSG-Z7002-2022", "附件A（核准证样式、填写说明及表A-1核准项目代码）", "检测机构名称、核准项目代码和检测方法覆盖", status="visual_verified")],
    "R04": [c("STD-TSG-31-2025", "3.1.3.1、3.1.3.3", "设计文件组成及批准签署层级"), c("STD-TSG-07-2019", "E1.4.1", "设计文件控制程序")],
    "R05": [c("STD-TSG-31-2025", "3.1.3.3", "设计文件批准签署"), c("STD-TSG-07-2019", "E1.4.1(7)、(9)", "设计文件审批和归档")],
    "R06": [c("STD-TSG-31-2025", "3.1.3.1、3.1.4.2", "计算书和管道系统设计"), c("STD-GBT-20801.1-2025", "6.7.5.5", "柔性分析要求")],
    "R07": [c("STD-TSG-31-2025", "2.1.4、3.1.3.3", "材料代用书面批准及设计文件签署"), c("STD-TSG-07-2019", "E1.4.1(8)", "设计文件更改控制")],
    "R08": [c("STD-TSG-31-2025", "1.7、3.1.3.2(1)-(2)", "技术标准效力和设计依据"), c("STD-TSG-07-2019", "M3.1.1(3)", "文件现行有效版本控制")],
    "R09": [c("STD-TSG-31-2025", "3.1.3.2(4)-(5)、3.1.8、3.1.9", "设计文件中的检验与试验要求"), c("STD-GBT-20801.1-2025", "8.3、8.6", "无损检测及压力/泄漏试验")],
    "R10": [c("STD-TSG-31-2025", "3.1.3.1", "境外或其他标准的符合性声明与比照表随设计文件提供", "other_standard_adopted")],
    "R11": [c("STD-TSG-07-2019", "E3.1.4-E3.1.5", "安装质量体系和安装安全性能"), c("STD-GB-50235-2010", "3.1.4(2)", "施工组织设计/施工方案批准与技术、安全交底", status="visual_verified")],
    "R24": [c("STD-TSG-Z6002-2010", "附件A A4.3、表A-1/A-2/A-4/A-6/A-7/A-8/A-9、A9", "焊工项目代号和覆盖范围", status="visual_verified"), c("STD-GBT-20801.1-2025", "7.4.1.1、7.4.1.5", "合格焊工施焊")],
    "R25": [c("STD-NBT-47014-2023", "4.2-4.4、第6章、附件A、附件G", "PQR/WPS评定、覆盖及格式"), c("STD-GBT-20801.1-2025", "7.4.1.1-7.4.1.4", "评定合格工艺与焊接工艺规程内容")],
    "R26": [c("STD-GBT-20801.1-2025", "7.4.2.1-7.4.2.2", "焊材选用、质量证明和包装标记"), c("STD-JBT-3223-2017", "第6章", "焊材验收和入库")],
    "R27": [c("STD-GBT-20801.1-2025", "7.4.2.3-7.4.2.6", "焊材储存、复验、烘干、标识"), c("STD-JBT-3223-2017", "7.1-7.3", "追溯、标记、烘干和保管")],
    "R28": [c("STD-GBT-20801.1-2025", "7.4.4.3.1-7.4.4.3.5", "错边、间隙、强力组对和附加应力")],
    "R29": [c("STD-GBT-20801.1-2025", "7.4.1.4、7.4.5.1-7.4.5.13、8.3.4", "施焊参数、过程检查和焊工标识")],
    "R30": [c("STD-GBT-20801.1-2025", "8.2.2、8.3.2及表43", "焊接接头目视检查和验收")],
    "R31": [c("STD-GBT-20801.1-2025", "7.4.11.1-7.4.11.5", "返修措施、批准、复检和记录")],
    "R32": [c("STD-GBT-20801.1-2025", "7.6.3", "焊后热处理工艺参数")],
    "R33": [c("STD-GBT-20801.1-2025", "7.6.5.2", "自动测温记录及校准仪表")],
    "R34": [c("STD-GBT-20801.1-2025", "7.6.5.2、7.6.6", "热处理曲线、报告和硬度")],
    "R35": [c("STD-NBT-47013.1-2015", "6.1-6.2、7.1", "无损检测质量管理及档案")],
    "R36": [c("STD-NBT-47013.1-2015", "4.3.1-4.3.2.4、7.2", "方法选择、工艺规程和作业指导书"), c("STD-GBT-20801.1-2025", "8.3.1、8.3.3.1", "检测等级、方法和比例")],
    "R37": [c("STD-NBT-47013.1-2015", "4.5、6.1-6.2", "检测程序与不符合控制"), c("STD-GBT-20801.1-2025", "8.1.3-8.1.4、8.3.3.4", "超标缺陷和累进检查")],
    "R38": [c("STD-NBT-47013.1-2015", "4.1.1-4.1.3", "检测人员资格、方法和级别覆盖")],
    "R39": [c("STD-NBT-47013.1-2015", "4.3.2.1-4.3.2.4、7.2", "检测工艺文件、规程、指导书及验证")],
    "R40": [c("STD-NBT-47013.1-2015", "7.3.1-7.4.4", "记录和报告字段、签署及保存")],
    "R41": [c("STD-NBT-47013.2-2015", "第4-8章", "射线检测技术、底片质量和评定", status="visual_verified"), c("STD-GBT-20801.1-2025", "8.3.3.2.1-8.3.3.2.4", "射线检测比例、技术等级和合格级别")],
    "R42": [c("STD-NBT-47013.2-2015", "第4-8章", "现场射线检测过程与底片", status="visual_verified"), c("STD-NBT-47013.11-2023", "4.4、5、6、8-10", "数字成像工艺、图像质量、评定和记录", "digital_radiography_used")],
    "R43": [c("STD-GBT-19285-2026", "4.2、5.1", "防腐材料及进场检验"), c("STD-GBT-20801.1-2025", "8.5", "质量证明、标记和检验文件")],
    "R44": [c("STD-GBT-19285-2026", "5.3.2-5.3.4", "补口补伤、回填后检验和资料")],
    "R45": [c("STD-GBT-19285-2026", "5.3.2.2(c)", "补口补伤100%漏点检测及修补复检"), c("STD-SYT-4113.11-2023", "第4-7章", "漏点检测仪器、试件、检测步骤和报告", status="visual_verified")],
    "R46": [c("STD-GBT-33378-2025", "6.3.2、6.4-6.5、6.9、7.4", "绝缘装置、牺牲阳极、外加电流及验收记录"), c("STD-GBT-21448-2017", "第5-7章、第9章", "强制电流/牺牲阳极、测试监测及施工调试", status="visual_verified")],
    "R47": [c("STD-GBT-20801.1-2025", "7.7.13.1-7.7.13.4、附录G G.9", "静电跨接、接地电阻和测试")],
    "R48": [c("STD-GBT-20801.1-2025", "7.4.6、附录G G.6.7.2", "焊缝布置和套管内管段")],
    "R49": [c("STD-GB-50235-2010", "7.1、7.3、7.9", "管道安装、钢制管道安装及防腐蚀衬里管道安装", status="visual_verified")],
    "R50": [c("STD-GBT-20801.1-2025", "附录G G.6.7.2(d)", "钢套管内绝缘支撑和电气隔离")],
    "R51": [c("STD-GBT-20801.1-2025", "7.7.12", "支吊架安装、导向和滑动要求")],
    "R52": [c("STD-GBT-20801.1-2025", "7.3、7.4、7.6、第8章", "现场预制、焊接、热处理及检查")],
    "R53": [c("STD-GBT-20801.1-2025", "7.4.4.3.4、7.7.1-7.7.4", "禁止强力对口及连接安装")],
    "R54": [c("STD-GBT-20801.1-2025", "7.7.11、附录P P.4", "补偿装置预拉伸/预压缩和安装")],
    "R55": [c("STD-GBT-20801.1-2025", "7.3.8、7.7.12", "支吊架制作、安装和检查")],
    "R56": [c("STD-TSG-92-2026", "第5章、附件D/E/F", "安全阀、爆破片、紧急切断阀选用与安装", "applicable_accessory_present", "visual_verified")],
    "R57": [c("STD-TSG-92-2026", "附件D及附录db", "安全阀校验项目、记录和报告", "safety_valve_present", "visual_verified")],
    "R58": [c("STD-TSG-92-2026", "附件F", "紧急切断阀功能和性能试验", "emergency_shutoff_valve_present", "visual_verified")],
    "R59": [c("STD-GBT-20801.1-2025", "8.6.1.1-8.6.1.4", "耐压试验方案、介质、压力和程序")],
    "R60": [c("STD-GBT-20801.1-2025", "8.6.1.2.5、8.6.1.3-8.6.1.4", "压力表数量/精度/量程及液压气压介质温度")],
    "R61": [c("STD-GBT-20801.1-2025", "8.6.1.1.4、8.6.1.3-8.6.1.4", "试验压力、保压时间和检查结果")],
    "R62": [c("STD-GBT-20801.1-2025", "8.6.1.1.8、8.7", "耐压试验记录字段和记录保存")],
    "R63": [c("STD-GBT-20801.1-2025", "6.7.5.5、8.6.1.7", "柔性分析及免压试验前置条件", "pressure_test_exemption_or_substitution")],
    "R64": [c("STD-GBT-20801.1-2025", "8.6.1.7、8.6.2.2", "替代性敏感泄漏试验", "pressure_test_exemption_or_substitution")],
    "R65": [c("STD-GBT-20801.1-2025", "8.3.1.2(h)、8.3.3、8.6.1.7", "免压试验时100%体积和表面无损检测", "pressure_test_exemption_or_substitution"), c("STD-NBT-47013.1-2015", "7.3-7.4", "无损检测记录报告可追溯")],
    "R66": [c("STD-GBT-20801.1-2025", "8.6.2.1-8.6.2.3", "泄漏试验介质、压力、温度和方法")],
    "R67": [c("STD-GBT-20801.1-2025", "8.6.2.2-8.6.2.3、8.7", "敏感泄漏/气密性试验及报告")],
    "R68": [c("STD-GBT-20801.1-2025", "7.9.1-7.9.6", "吹扫清洗方案、介质、顺序和验收"), c("STD-GB-50235-2010", "第9章（9.1-9.7）", "水冲洗、空气/蒸汽吹扫、脱脂、化学/油清洗", status="visual_verified")],
    "R12": [c("STD-TSG-31-2025", "1.10、2.2", "元件制造许可和监督管理"), c("STD-SAMR-2021-41", "附件1：特种设备生产单位许可目录", "元件许可范围", status="visual_verified")],
    "R13": [c("STD-TSG-31-2025", "1.8、2.1.3", "型式试验和新材料技术评审")],
    "R14": [c("STD-GBT-8163-2018", "第6-8章", "试验方法、检验规则、包装标志和质量证明", "product_is_gbt8163", "visual_verified"), c("STD-GBT-12771-2019", "6.9、第8章、9.1-9.2", "无损检测、检验规则、标志和质量证明", "product_is_gbt12771")],
    "R15": [c("STD-TSG-31-2025", "2.1.2(1)-(6)", "境外牌号材料验证复验、工艺评定和企业标准", "overseas_product_or_material")],
    "R16": [c("STD-GBT-12459-2025", "第10-11章", "管件标志和产品质量证明", "product_is_gbt12459"), c("STD-GBT-13401-2025", "第8章、第10-11章", "管件检验试验、表面防护包装和质量证明", "product_is_gbt13401", "visual_verified"), c("STD-GBT-14976-2025", "7.3、7.7、第9-11章", "液压/无损检测、试验方法、检验规则和质量证明", "product_is_gbt14976", "visual_verified")],
    "R17": [c("STD-GBT-20801.1-2025", "8.5", "材料和组成件合格证、质量证明及标记"), c("STD-TSG-07-2019", "M3.4", "材料验收、复验和标识控制")],
    "R18": [c("STD-TSG-31-2025", "2.1.2(3)", "境外牌号材料验证性复验"), c("STD-NBT-47013.1-2015", "7.3-7.4", "无损检测记录报告")],
    "R19": [c("STD-TSG-31-2025", "2.1.2(1)-(6)", "境外牌号材料的适用、复验、工艺评定及归档", "overseas_grade_material")],
    "R20": [c("STD-TSG-31-2025", "1.8、2.1.3", "新材料型式试验、技术评审和批准", "new_material_used")],
    "R21": [c("STD-GBT-20801.1-2025", "7.3.2", "材料标记和标记移植"), c("STD-TSG-07-2019", "M3.4", "材料标识和可追溯控制")],
    "R22": [c("STD-TSG-31-2025", "2.1.4", "材料代用取得原设计单位书面批准"), c("STD-TSG-07-2019", "M3.4", "材料代用控制")],
    "R23": [c("STD-GBT-13927-2022", "5.4、5.6-5.9、6.1-6.3、7.1-7.4", "阀门压力表、介质、压力、持续时间和验收证明"), c("STD-GBT-26480-2011", "第5-8章", "壳体、高压/低压密封试验", "design_specifies_gbt26480", "visual_verified")],
    "R69": [c("STD-TSG-D7006-2020", "附件G G1-G5", "施工单位资源条件、质量保证体系保持改进、许可制度执行和问题处理的项目评价")],
}


# (locator clause label, PDF start page, PDF end page, verification method).
# Composite references deliberately have multiple locators when their clauses
# are non-contiguous, so the UI can jump to every cited source section.
LocatorSpec = tuple[str, int, int, str]
PROFESSIONAL_LOCATOR_SPECS: dict[tuple[str, str], list[LocatorSpec]] = {}


def add_locator_specs(ref: str, values: dict[str, list[LocatorSpec]]) -> None:
    for clause_no, specs in values.items():
        key = (ref, clause_no)
        assert key not in PROFESSIONAL_LOCATOR_SPECS
        PROFESSIONAL_LOCATOR_SPECS[key] = specs


T = "text_verified"
V = "visual_verified"
add_locator_specs("STD-TSG-D7006-2020", {
    "附件G G1-G5": [("附件G G1-G5", 38, 39, T)],
})
add_locator_specs("STD-GB-50235-2010", {
    "3.1.4(2)": [("3.1.4(2)", 18, 18, V)],
    "7.1、7.3、7.9": [("7.1", 39, 40, V), ("7.3", 41, 48, V), ("7.9", 49, 51, V)],
    "第9章（9.1-9.7）": [("9.1-9.7", 66, 70, V)],
})
add_locator_specs("STD-GBT-12459-2025", {
    "第10-11章": [("第10章", 41, 42, T), ("第11章", 42, 42, T)],
})
add_locator_specs("STD-GBT-12771-2019", {
    "6.9、第8章、9.1-9.2": [("6.9", 13, 13, T), ("第8章", 14, 15, T), ("9.1-9.2", 15, 15, T)],
})
add_locator_specs("STD-GBT-13401-2025", {
    "第8章、第10-11章": [("第8章", 14, 20, T), ("第10-11章", 21, 21, T)],
})
add_locator_specs("STD-GBT-13927-2022", {
    "5.4、5.6-5.9、6.1-6.3、7.1-7.4": [("5.4、5.6-5.9", 2, 2, T), ("6.1-6.3", 2, 3, T), ("7.1-7.4", 3, 3, T)],
})
add_locator_specs("STD-GBT-14976-2025", {
    "7.3、7.7、第9-11章": [("7.3", 16, 16, T), ("7.7", 17, 17, T), ("第9章", 21, 21, T), ("第10-11章", 22, 22, T)],
})
add_locator_specs("STD-GBT-19285-2026", {
    "4.2、5.1": [("4.2", 9, 9, T), ("5.1", 9, 10, T)],
    "5.3.2-5.3.4": [("5.3.2-5.3.4", 13, 13, T)],
    "5.3.2.2(c)": [("5.3.2.2(c)", 13, 13, T)],
})
add_locator_specs("STD-GBT-20801.1-2025", {
    "6.7.5.5": [("6.7.5.5", 76, 76, T)],
    "6.7.5.5、8.6.1.7": [("6.7.5.5", 76, 76, T), ("8.6.1.7", 128, 128, T)],
    "7.3.2": [("7.3.2", 88, 88, T)],
    "7.3.8、7.7.12": [("7.3.8", 92, 92, T), ("7.7.12", 114, 115, T)],
    "7.3、7.4、7.6、第8章": [("7.3、7.4、7.6", 88, 117, T), ("第8章", 118, 130, T)],
    "7.4.1.1-7.4.1.4": [("7.4.1.1-7.4.1.4", 92, 92, T)],
    "7.4.1.1、7.4.1.5": [("7.4.1.1", 92, 92, T), ("7.4.1.5", 92, 93, T)],
    "7.4.1.4、7.4.5.1-7.4.5.13、8.3.4": [("7.4.1.4", 92, 92, T), ("7.4.5.1-7.4.5.13", 96, 97, T), ("8.3.4", 124, 124, T)],
    "7.4.11.1-7.4.11.5": [("7.4.11.1-7.4.11.5", 102, 102, T)],
    "7.4.2.1-7.4.2.2": [("7.4.2.1-7.4.2.2", 93, 93, T)],
    "7.4.2.3-7.4.2.6": [("7.4.2.3-7.4.2.6", 93, 93, T)],
    "7.4.4.3.1-7.4.4.3.5": [("7.4.4.3.1-7.4.4.3.5", 94, 95, T)],
    "7.4.4.3.4、7.7.1-7.7.4": [("7.4.4.3.4", 95, 95, T), ("7.7.1-7.7.4", 110, 113, T)],
    "7.4.6、附录G G.6.7.2": [("7.4.6", 97, 97, T), ("附录G G.6.7.2", 235, 235, T)],
    "7.6.3": [("7.6.3", 104, 108, T)],
    "7.6.5.2": [("7.6.5.2", 109, 109, T)],
    "7.6.5.2、7.6.6": [("7.6.5.2、7.6.6", 109, 109, T)],
    "7.7.11、附录P P.4": [("7.7.11", 114, 114, T), ("附录P P.4", 274, 274, T)],
    "7.7.12": [("7.7.12", 114, 115, T)],
    "7.7.13.1-7.7.13.4、附录G G.9": [("7.7.13.1-7.7.13.4", 115, 115, T), ("附录G G.9", 236, 237, T)],
    "7.9.1-7.9.6": [("7.9.1-7.9.6", 116, 117, T)],
    "8.1.3-8.1.4、8.3.3.4": [("8.1.3-8.1.4", 118, 118, T), ("8.3.3.4", 124, 124, T)],
    "8.2.2、8.3.2及表43": [("8.2.2", 118, 119, T), ("8.3.2及表43", 120, 122, T)],
    "8.3.1.2(h)、8.3.3、8.6.1.7": [("8.3.1.2(h)、8.3.3", 119, 124, T), ("8.6.1.7", 128, 128, T)],
    "8.3.1、8.3.3.1": [("8.3.1", 119, 120, T), ("8.3.3.1", 122, 122, T)],
    "8.3.3.2.1-8.3.3.2.4": [("8.3.3.2.1-8.3.3.2.4", 123, 123, T)],
    "8.3、8.6": [("8.3", 119, 124, T), ("8.6", 125, 130, T)],
    "8.5": [("8.5", 124, 124, T)],
    "8.6.1.1-8.6.1.4": [("8.6.1.1-8.6.1.4", 125, 129, T)],
    "8.6.1.1.4、8.6.1.3-8.6.1.4": [("8.6.1.1.4", 126, 126, T), ("8.6.1.3-8.6.1.4", 127, 129, T)],
    "8.6.1.1.8、8.7": [("8.6.1.1.8", 126, 126, T), ("8.7", 130, 130, T)],
    "8.6.1.2.5、8.6.1.3-8.6.1.4": [("8.6.1.2.5", 127, 127, T), ("8.6.1.3-8.6.1.4", 127, 129, T)],
    "8.6.1.7、8.6.2.2": [("8.6.1.7", 128, 128, T), ("8.6.2.2", 129, 130, T)],
    "8.6.2.1-8.6.2.3": [("8.6.2.1-8.6.2.3", 129, 130, T)],
    "8.6.2.2-8.6.2.3、8.7": [("8.6.2.2-8.6.2.3", 129, 130, T), ("8.7", 130, 130, T)],
    "附录G G.6.7.2(d)": [("附录G G.6.7.2(d)", 235, 235, T)],
})
add_locator_specs("STD-GBT-21448-2017", {
    "第5-7章、第9章": [("第5章", 11, 14, V), ("第6章", 15, 18, V), ("第7章", 19, 22, V), ("第9章", 23, 26, V)],
})
add_locator_specs("STD-GBT-26480-2011", {
    "第5-8章": [("第5章", 5, 8, V), ("第6章", 8, 8, V), ("第7章", 9, 10, V), ("第8章", 10, 10, V)],
})
add_locator_specs("STD-GBT-33378-2025", {
    "6.3.2、6.4-6.5、6.9、7.4": [("6.3.2", 18, 18, T), ("6.4-6.5", 18, 19, T), ("6.9", 20, 20, T), ("7.4", 21, 22, T)],
})
add_locator_specs("STD-GBT-8163-2018", {
    "第6-8章": [("第6章", 14, 14, V), ("第7-8章", 15, 15, V)],
})
add_locator_specs("STD-JBT-3223-2017", {
    "7.1-7.3": [("7.1-7.3", 7, 8, V)],
    "第6章": [("第6章", 5, 7, V)],
})
add_locator_specs("STD-NBT-47013.1-2015", {
    "4.1.1-4.1.3": [("4.1.1-4.1.3", 7, 7, V)],
    "4.3.1-4.3.2.4、7.2": [("4.3.1-4.3.2.4", 8, 10, V), ("7.2", 14, 14, V)],
    "4.3.2.1-4.3.2.4、7.2": [("4.3.2.1-4.3.2.4", 8, 10, V), ("7.2", 14, 14, V)],
    "4.5、6.1-6.2": [("4.5", 10, 10, V), ("6.1-6.2", 13, 13, V)],
    "6.1-6.2、7.1": [("6.1-6.2", 13, 13, V), ("7.1", 14, 14, V)],
    "7.3-7.4": [("7.3-7.4", 14, 16, V)],
    "7.3.1-7.4.4": [("7.3.1-7.4.4", 14, 16, V)],
})
add_locator_specs("STD-NBT-47013.11-2023", {
    "4.4、5、6、8-10": [("4.4", 15, 17, T), ("第5章", 19, 20, T), ("第6章", 20, 24, T), ("第8-10章", 26, 27, T)],
})
add_locator_specs("STD-NBT-47013.2-2015", {
    "第4-8章": [("第4章", 8, 11, V), ("第5章", 12, 23, V), ("第6章", 24, 28, V), ("第7章", 29, 32, V), ("第8章", 33, 33, V)],
})
add_locator_specs("STD-NBT-47014-2023", {
    "4.2-4.4、第6章、附件A、附件G": [("4.2-4.4", 12, 12, T), ("第6章", 13, 63, T), ("附件A", 64, 77, T), ("附件G", 78, 91, T)],
})
add_locator_specs("STD-SAMR-2021-41", {
    "附件1：特种设备生产单位许可目录": [("附件1", 3, 12, V)],
})
add_locator_specs("STD-SYT-4113.11-2023", {
    "第4-7章": [("第4-5章", 7, 8, V), ("第6章", 8, 8, V), ("第7章", 9, 9, V)],
})
add_locator_specs("STD-TSG-07-2019", {
    "E1.1、E1.2.2": [("E1.1", 70, 70, T), ("E1.2.2", 71, 71, T)],
    "E1.4.1": [("E1.4.1", 72, 72, T)],
    "E1.4.1(7)、(9)": [("E1.4.1(7)、(9)", 72, 72, T)],
    "E1.4.1(8)": [("E1.4.1(8)", 72, 72, T)],
    "E3.1.4-E3.1.5": [("E3.1.4-E3.1.5", 89, 89, T)],
    "E3.1、E3.2.5-E3.2.7、表E-13-E-14": [("E3.1", 87, 89, T), ("E3.2.5-E3.2.7", 94, 95, T), ("表E-13-E-14", 96, 97, T)],
    "M3.1.1(3)": [("M3.1.1(3)", 167, 167, T)],
    "M3.4": [("M3.4", 169, 169, T)],
})
add_locator_specs("STD-TSG-31-2025", {
    "1.10、2.2": [("1.10", 7, 7, V), ("2.2", 9, 10, V)],
    "1.7、3.1.3.2(1)-(2)": [("1.7", 7, 7, V), ("3.1.3.2(1)-(2)", 19, 19, V)],
    "1.8、2.1.3": [("1.8", 7, 7, V), ("2.1.3", 8, 8, V)],
    "2.1.2(1)-(6)": [("2.1.2(1)-(6)", 8, 8, V)],
    "2.1.2(3)": [("2.1.2(3)", 8, 8, V)],
    "2.1.4": [("2.1.4", 8, 8, V)],
    "2.1.4、3.1.3.3": [("2.1.4", 8, 8, V), ("3.1.3.3", 19, 19, V)],
    "3.1.1-3.1.2": [("3.1.1", 18, 18, V), ("3.1.2", 19, 19, V)],
    "3.1.3.1": [("3.1.3.1", 19, 19, V)],
    "3.1.3.1、3.1.3.3": [("3.1.3.1、3.1.3.3", 19, 19, V)],
    "3.1.3.1、3.1.4.2": [("3.1.3.1", 19, 19, V), ("3.1.4.2", 20, 20, V)],
    "3.1.3.2(4)-(5)、3.1.8、3.1.9": [("3.1.3.2(4)-(5)", 19, 19, V), ("3.1.8、3.1.9", 21, 21, V)],
    "3.1.3.3": [("3.1.3.3", 19, 19, V)],
})
add_locator_specs("STD-TSG-92-2026", {
    "第5章、附件D/E/F": [("第5章", 15, 15, V), ("附件D", 21, 37, V), ("附件E", 38, 44, V), ("附件F", 45, 51, V)],
    "附件D及附录db": [("附件D", 21, 37, V), ("附录db", 33, 33, V)],
    "附件F": [("附件F", 45, 51, V)],
})
add_locator_specs("STD-TSG-Z6002-2010", {
    "附件A A4.3、表A-1/A-2/A-4/A-6/A-7/A-8/A-9、A9": [("A4.3", 16, 17, V), ("表A-1/A-2/A-4/A-6/A-7/A-8/A-9", 18, 35, V), ("A9", 43, 44, V)],
})
add_locator_specs("STD-TSG-Z7002-2022", {
    "附件A（核准证样式、填写说明及表A-1核准项目代码）": [("附件A证书样式", 10, 10, V), ("填写说明及表A-1", 11, 12, V)],
})


APPLICABILITY = {
    "R69": ("manual", "每个压力管道施工工程项目均应由监检人员结合全项目监检结果进行评价并签发评价报告。"),
    "R10": ("conditional", "设计文件采用其他标准（GB/T 20801、GB/T 32270、GB/T 34275以外的标准）时适用；否则结论为不适用。"),
    "R45": ("conditional", "存在埋地防腐层、补口或补伤时适用。"),
    "R46": ("conditional", "设计设置阴极保护或杂散电流排流装置时适用。"),
    "R48": ("conditional", "工程存在穿越或跨越管段时适用。"),
    "R49": ("conditional", "工程存在穿越或跨越施工时适用。"),
    "R50": ("conditional", "穿越管段设置钢套管时适用。"),
    "R51": ("conditional", "设计要求管道与支撑绝缘时适用。"),
    "R56": ("conditional", "按项目实际配置的安全阀、爆破片或紧急切断阀分别进入对应条款分支。"),
    "R57": ("conditional", "项目设置安全阀时适用。"),
    "R58": ("conditional", "项目设置紧急切断阀时适用。"),
    "R63": ("conditional", "设计提出免除或替代耐压试验时适用。"),
    "R64": ("conditional", "采用替代性敏感泄漏试验时适用。"),
    "R65": ("conditional", "免除或替代耐压试验时适用。"),
    "R15": ("conditional", "压力管道元件或安全附件为境外制造时适用。"),
    "R19": ("conditional", "使用境外牌号材料时适用。"),
    "R20": ("conditional", "使用未列入适用材料标准的新材料时适用。"),
}


BATCHES = [
    ("BATCH-01", "资质与设计", [f"R{i:02d}" for i in range(1, 12)]),
    ("BATCH-02", "材料与阀门", [f"R{i:02d}" for i in range(12, 24)]),
    ("BATCH-03", "焊接与热处理", [f"R{i:02d}" for i in range(24, 35)]),
    ("BATCH-04", "无损检测", [f"R{i:02d}" for i in range(35, 43)]),
    ("BATCH-05", "防腐、穿跨越、安装与安全附件", [f"R{i:02d}" for i in range(43, 59)]),
    ("BATCH-06", "耐压、泄漏、吹洗与质量体系评价", [f"R{i:02d}" for i in range(59, 70)]),
]
BATCH_BY_RULE = {rule_id: batch_id for batch_id, _, rules in BATCHES for rule_id in rules}


def clean_checks(rule: dict[str, object]) -> list[str]:
    if rule.get("sourceRuleId") == "R69":
        return [
            "核验监检人员签发的评价报告是否存在且覆盖当前工程，并包含评价结果、评价人员、评价日期和签发信息；Tool不得生成或改写评价结果。",
            "核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。",
        ]
    execution = rule.get("aiExecution") or {}
    candidates = list(execution.get("verificationSteps") or []) + list(execution.get("acceptanceCriteria") or [])
    checks: list[str] = []
    for raw in candidates:
        text = " ".join(str(raw).split())
        if len(text) < 8 or text in checks or text.startswith("二者不一致"):
            continue
        checks.append(text)
        if len(checks) == 4:
            break
    checks.append("核验结论引用的文件、页码/坐标和原文字段可追溯；证据缺失、冲突或OCR低置信度时不得判定为符合。")
    return checks


def dump_yaml(path: Path, data: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")


def make_locator(
    standard_ref: str,
    clause_no: str,
    start_page: int,
    end_page: int,
    verification_status: str,
) -> dict[str, object]:
    digest = hashlib.sha1(
        f"{standard_ref}|{clause_no}|{start_page}|{end_page}".encode("utf-8")
    ).hexdigest()[:12].upper()
    return {
        "locatorId": f"LOC-{digest}",
        "clauseNo": clause_no,
        "sourcePage": start_page,
        "startPage": start_page,
        "endPage": end_page,
        "precision": "page" if start_page == end_page else "page_range",
        "verificationStatus": verification_status,
    }


def enrich_professional_clause(item: dict[str, str]) -> dict[str, object]:
    standard_ref = item["standardRef"]
    specs = PROFESSIONAL_LOCATOR_SPECS[(standard_ref, item["clauseNo"])]
    locators = [make_locator(standard_ref, *spec) for spec in specs]
    knowledge_file_id, document_version_id = KNOWLEDGE_DOCUMENTS[standard_ref]
    result: dict[str, object] = dict(item)
    result.update({
        "knowledgeFileId": knowledge_file_id,
        "documentVersionId": document_version_id,
        "sourcePage": locators[0]["sourcePage"],
        "startPage": min(int(locator["startPage"]) for locator in locators),
        "endPage": max(int(locator["endPage"]) for locator in locators),
        "sourceLocatorId": locators[0]["locatorId"],
        "locatorPrecision": "page" if all(locator["precision"] == "page" for locator in locators) else "page_range",
        "locatorVerification": item["verificationStatus"],
        "locators": locators,
    })
    return result


def build() -> None:
    rules = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))["ruleSets"]
    by_source = {rule["sourceRuleId"]: rule for rule in rules}
    primary = primary_map()
    expected = {f"R{i:02d}" for i in range(1, 70)}
    assert set(by_source) == expected
    assert set(primary) == expected
    assert set(SUPPLEMENTAL) == expected
    expected_professional_keys = {
        (item["standardRef"], item["clauseNo"])
        for items in SUPPLEMENTAL.values()
        for item in items
    }
    assert set(PROFESSIONAL_LOCATOR_SPECS) == expected_professional_keys
    assert set(KNOWLEDGE_DOCUMENTS) == {item["id"] for item in CATALOG}

    catalog = {
        "standardCatalogSet": {"id": "engineering-inspection-standard-catalog-v1", "schemaVersion": "standard-catalog-v1", "version": "2026.07.14", "lifecycleStatus": "published"},
        "standardCatalog": CATALOG,
    }
    dump_yaml(PACK_DIR / "standard_clause_catalog.yaml", catalog)

    bindings = []
    for source_id in sorted(expected):
        rule = by_source[source_id]
        ref, clause, page = primary[source_id]
        normalized = clause.replace(".", "-").replace("(", "-").replace(")", "")
        primary_locator = make_locator(ref, clause, page, page, "source_verified")
        knowledge_file_id, document_version_id = KNOWLEDGE_DOCUMENTS[ref]
        bindings.append({
            "bindingId": f"BIND-{source_id}-{normalized}",
            "ruleId": rule["id"], "sourceRuleId": source_id, "nodeId": int(rule["nodeIds"][0]),
            "standardRef": ref, "clauseNo": clause, "bindingRole": "primary", "applicability": "always" if source_id != "R10" else "other_standard_adopted",
            "lifecycleStatus": "published", "verificationStatus": "source_verified",
            "knowledgeFileId": knowledge_file_id, "documentVersionId": document_version_id,
            "sourcePage": page, "startPage": page, "endPage": page,
            "sourceLocatorId": primary_locator["locatorId"], "locatorPrecision": "page",
            "locators": [primary_locator],
        })
    binding_data = {
        "standardClauseBindingSet": {
            "id": "engineering-inspection-standard-clause-bindings-v2", "schemaVersion": "standard-clause-binding-v1", "version": "2026.07.14",
            "lifecycleStatus": "published", "sourceBusinessRules": "rules/业务规则.md",
            "runtimePolicy": {"consumableLifecycleStatuses": ["published"], "requiredVerificationStatus": "source_verified", "primaryBindingCardinality": "exactly_one_per_rule", "freezeIntoReviewRunSnapshot": True},
        },
        "standardClauseBindings": bindings,
    }
    dump_yaml(PACK_DIR / "standard_clause_bindings.yaml", binding_data)

    atomic_checks = []
    packages = []
    issues = []
    binding_by_rule = {item["sourceRuleId"]: item for item in bindings}
    for source_id in sorted(expected):
        rule = by_source[source_id]
        node_id = int(rule["nodeIds"][0])
        checks = clean_checks(rule)
        check_ids = []
        for index, text in enumerate(checks, 1):
            check_id = f"AC-{source_id}-{index:02d}"
            check_ids.append(check_id)
            atomic_checks.append({
                "id": check_id, "sourceRuleId": source_id, "ruleId": rule["id"], "nodeId": node_id,
                "name": f"{rule['name']}·原子项{index}", "checkType": "evidence_and_deterministic_rule",
                "instruction": text, "evidenceRequired": True,
                "failurePolicy": "evidence_insufficient" if index == len(checks) else "business_rule_result",
            })
        applicability_type, applicability_text = APPLICABILITY.get(source_id, ("always", "本业务节点进入复核流程时适用。"))
        professional = [enrich_professional_clause(item) for item in SUPPLEMENTAL[source_id]]
        for item in professional:
            if item["verificationStatus"] != "source_verified":
                issues.append({
                    "issue_id": f"ISSUE-{source_id}-{len(issues)+1:03d}", "source_rule_id": source_id, "node_id": node_id,
                    "standard_ref": item["standardRef"], "clause_no": item["clauseNo"], "status": "closed_with_page_locator" if item["verificationStatus"] == "visual_verified" else "open_candidate",
                    "action": "已完成人工可视复核并记录PDF页级定位；后续可在条款摘录卡中继续补充文本块或坐标级定位。",
                })
        packages.append({
            "packageId": f"CLAUSE-PKG-{source_id}", "batchId": BATCH_BY_RULE[source_id], "sourceRuleId": source_id,
            "ruleId": rule["id"], "nodeId": node_id, "nodeName": rule["name"], "inspectionCategory": rule.get("inspectionCategory") or rule.get("businessModule") or "",
            "lifecycleStatus": "published", "primaryBindingId": binding_by_rule[source_id]["bindingId"],
            "applicability": {"type": applicability_type, "expression": applicability_text},
            "professionalClauses": professional, "atomicCheckIds": check_ids,
            "requiredEvidence": list(dict.fromkeys((rule.get("aiExecution") or {}).get("requiredEvidence") or []))[:8],
            "decisionModel": {
                "resultValues": ["符合", "不符合", "证据不足", "不适用", "待人工确认"],
                "ruleExecution": "deterministic_tools_only",
                "llmRole": "仅汇总全项目证据并校验人工评价报告的完整性；不得生成或覆盖监检人员评价结论" if source_id == "R69" else "调用工具、组织证据、解释已返回结果，不自行改写数值或条款判据",
                "failClosed": True,
                "automatedDecisionAllowed": source_id != "R69",
            },
        })
    dump_yaml(PACK_DIR / "atomic_checks.yaml", {
        "atomicCheckSet": {"id": "engineering-inspection-atomic-checks-v1", "schemaVersion": "atomic-check-v1", "version": "2026.07.14", "lifecycleStatus": "published"},
        "atomicChecks": atomic_checks,
    })
    dump_yaml(PACK_DIR / "standard_clause_packages.yaml", {
        "standardClausePackageSet": {
            "id": "engineering-inspection-standard-clause-packages-v1", "schemaVersion": "standard-clause-package-v1", "version": "2026.07.14", "lifecycleStatus": "published",
            "batches": [{"id": batch_id, "name": name, "sourceRuleIds": ids} for batch_id, name, ids in BATCHES],
            "runtimePolicy": {"resolveBy": ["businessPackVersion", "sourceRuleId", "nodeId"], "freezeIntoReviewRunSnapshot": True, "llmMaySelectClause": False, "llmMayChangeDeterministicResult": False},
        },
        "standardClausePackages": packages,
    })

    catalog_by_id = {item["id"]: item for item in CATALOG}
    lines = [
        "# 业务节点具体标准条款审核矩阵", "",
        "> 版本：2026.07.14。主条款已经逐条核验并发布；专业补充条款中的 `visual_verified` 表示扫描件已完成人工可视复核，运行时仍以主条款和已固化业务规则为判断入口。", "",
        "| 批次 | 规则/节点 | 业务审核节点 | 主条款（直接监检依据） | 专业执行条款 | 适用条件 | 原子项 |", "|---|---:|---|---|---|---|---:|",
    ]
    for package in packages:
        binding = binding_by_rule[package["sourceRuleId"]]
        primary_text = f"{catalog_by_id[binding['standardRef']]['code']} {binding['clauseNo']}（PDF {binding['sourcePage']}）"
        professional_text = "<br>".join(
            f"{catalog_by_id[item['standardRef']]['code']} {item['clauseNo']}（{', '.join('PDF ' + str(locator['startPage']) + (('-' + str(locator['endPage'])) if locator['endPage'] != locator['startPage'] else '') for locator in item['locators'])}）：{item['purpose']}"
            for item in package["professionalClauses"]
        )
        lines.append(f"| {package['batchId']} | {package['sourceRuleId']} / {package['nodeId']} | {package['nodeName']} | {primary_text} | {professional_text} | {package['applicability']['expression']} | {len(package['atomicCheckIds'])} |")
    lines.extend([
        "", "## 运行约束", "",
        "- 后端按 `sourceRuleId + nodeId + 业务包版本`读取固定条款包，并将版本快照固化到 ReviewRun。",
        "- 数值比较、日期覆盖、证照范围、比例、完整性和条件分支必须由确定性工具执行；LLM 只调用工具、串联证据并解释工具返回值。",
        "- 证据不足、字段冲突、条款包不完整或工具失败时，结论只能是“证据不足”或“待人工确认”，不得推断为“符合”。",
        "- 前端展示标准号、条款号、证据定位、原子项执行轨迹、工具输入输出摘要和 AI 结论；`reasoning_content` 可作为模型流式过程日志，但不替代本矩阵的审计判据。",
    ])
    (DOCS_DIR / "业务节点具体标准条款审核矩阵.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (DOCS_DIR / "条款核验问题清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["issue_id", "source_rule_id", "node_id", "standard_ref", "clause_no", "status", "action"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(issues)

    print(f"generated catalog={len(CATALOG)} bindings={len(bindings)} packages={len(packages)} atomic_checks={len(atomic_checks)} issues={len(issues)}")


if __name__ == "__main__":
    build()
