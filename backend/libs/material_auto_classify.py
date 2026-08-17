"""上传的资料自动归类——施工方不必先选类别（0817 第 2 条）。

## 用户要的

    「不需要资料对应上传，直接资料上传后自动识别类别，
      提示缺的内容以及未通过的部分」

也就是把分类从「用户的输入」变成「系统的输出」。

## 词典不用另造

backend/config/material_review_points.json 里已经有 164 条资料审查点，
每条都带 materialTypeName（制造单位许可证、材料复验报告、焊接工艺评定……）
和 materialCategory。**这就是现成的分类词典**，另建一份必然和它漂移。

## 三条设计原则

1. **匹配到的最长名字取胜**，不是第一个命中的。
   「制造单位许可证」和「许可证」都能命中同一个文件名，
   前者更具体。前端那份分类器就是栽在「首个匹配即胜」上
   （见 frontend/.../contractorMaterialCategories.ts）。

2. **拿不准就说拿不准。** 返回 None 而不是猜一个类别。
   猜错的类别会让规则去错的地方取证，最后表现为「资料传了却判缺项」——
   而界面上「分对了」和「分错了」长得一模一样。

3. **必须能人工改。** 自动分类一定会错（第 1 条就是分类错的例子），
   没有纠正出口的自动化，用户错一次就没有办法了。
   这里只负责给出建议和理由，改不改由调用方和界面决定。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG = Path(__file__).resolve().parents[1] / "config" / "material_review_points.json"

# 太短的名字当关键词会误伤：「材料」「阀门」这种两字词几乎出现在所有文件名里。
MIN_KEYWORD_LENGTH = 3


# 现实里的文件名不会照抄审查点的名字。
#
# 审查点叫「制造单位许可证」，证书封面和文件名写的是「特种设备生产许可证」；
# 审查点叫「设计单位许可证」，现场存的是「特种设备设计资质.png」。
# 只按审查点名字匹配的话，**最常见的几种证照一个都认不出来**。
#
# 别名只补**名字**，类别仍然从 material_review_points.json 里取——
# 否则这里就成了第二份分类定义，迟早和配置漂移。
ALIASES: dict[str, str] = {
    "特种设备生产许可证": "manufacturing_license",
    "生产许可证": "manufacturing_license",
    "制造许可证": "manufacturing_license",
    "元件制造许可证": "manufacturing_license",
    "特种设备设计资质": "design_license",
    "设计资质": "design_license",
    "设计许可证": "design_license",
    "安装许可证": "construction_license",
    "施工许可证": "construction_license",
    "无损检测机构核准": "ndt_org_certificate",
    "检测机构资质": "ndt_org_certificate",
    "焊工证": "welder_certificate",
    "焊工资格证": "welder_certificate",
}


@lru_cache(maxsize=1)
def _dictionary() -> tuple[tuple[str, str, str], ...]:
    """(关键词, 资料类别, 资料类型编码)，按关键词长度降序。

    降序是为了「最长命中取胜」能一遍扫完就得到答案。
    """
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()

    entries: dict[str, tuple[str, str]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            name = str(node.get("materialTypeName") or "").strip()
            category = str(node.get("materialCategory") or "").strip()
            code = str(node.get("materialTypeCode") or "").strip()
            if name and category and len(name) >= MIN_KEYWORD_LENGTH:
                entries.setdefault(name, (category, code))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)

    # 别名按 code 反查类别。查不到就丢弃——**宁可少认一种，
    # 也不要凭一个失效的别名把资料塞进错的类别**。
    by_code = {code: (name, category) for name, (category, code) in entries.items() if code}
    for alias, code in ALIASES.items():
        target = by_code.get(code)
        if target and alias not in entries:
            entries[alias] = (target[1], code)

    return tuple(
        (name, category, code)
        for name, (category, code) in sorted(entries.items(), key=lambda kv: -len(kv[0]))
    )


def _normalize(text: str) -> str:
    # 去掉空白和常见分隔符：「特种设备生产许可证-贵州化工.pdf」也要能命中
    return re.sub(r"[\s_\-—－()（）\[\]【】]+", "", str(text or "")).lower()


def classify_material(file_name: str = "", ocr_text: str = "") -> dict[str, Any] | None:
    """给一份资料建议类别。拿不准返回 None。

    文件名优先于正文：文件名是人**特意起的**，正文里出现「制造许可证」
    可能只是引用了一句法规。正文只在文件名认不出来时才用，
    并且把 source 标出来——两种来源的可信度不一样，界面上要能区分。
    """
    for source, raw in (("fileName", file_name), ("ocrText", ocr_text)):
        haystack = _normalize(raw)
        if not haystack:
            continue
        for name, category, code in _dictionary():
            if _normalize(name) in haystack:
                return {
                    "materialCategory": category,
                    "materialTypeCode": code,
                    "materialTypeName": name,
                    "matchedBy": source,
                    # 说清楚**凭什么**这么分。只给结论不给依据的话，
                    # 用户发现分错了也不知道该改什么。
                    "reason": f"{'文件名' if source == 'fileName' else '正文'}中出现「{name}」",
                }
    return None


def known_categories() -> set[str]:
    """配置里存在的全部资料类别。

    给「人工改类别」做白名单：允许任意字符串的话，规则按类别取证时
    永远取不到，而界面上看着「已经归好类了」——又一个静默失败。
    """
    return {category for _, category, _ in _dictionary() if category}
