"""字段置信度的判定口径只有一份（0817 第 7 条）。

## 用户说「把置信度调低」

0.85 对 OCR 来说是很严的线：常规印刷体 PaddleOCR 大多落在 0.75~0.95，
稍有噪点就掉到 0.8 以下，于是**几乎每个字段后面都跟着「需回原文核对」**。
提示到处都是就等于没有提示——真正该看的那几个反而淹没了。

## 但更要紧的是：这条线原先散在 6 个地方

    libs/db/repository.py   写入时定 reviewStatus
    libs/db/repository.py   统计 low_conf
    apps/api/routes.py      阻塞项清单
    apps/api/routes.py      lowConfidenceFieldCount
    apps/api/routes.py      ×2 其它统计

改一处的后果是「字段标着已确认，却仍然挂在阻塞项里」——
两个界面各说各的，而没有任何东西会报错。

## 阈值管的不是对错

它管的是「要不要提醒人来看一眼」。值本身对不对由抽取环节的护栏负责
（见 test_license_scope_extraction）。**把阈值调低来减少报警，
同时指望它拦住错值，两头都会落空。**
"""

from __future__ import annotations

import re
from pathlib import Path

from libs.field_confidence import (
    DEFAULT_FIELD_CONFIRM_CONFIDENCE,
    field_confirm_confidence,
    field_review_status,
)

BACKEND = Path(__file__).resolve().parents[1]


def test_默认阈值已经调低():
    assert DEFAULT_FIELD_CONFIRM_CONFIDENCE == 0.70
    assert field_confirm_confidence() == 0.70


def test_三态分开():
    """「没有分数」和「分数低」是两种不同的不确定，处置方式不同。"""
    assert field_review_status(0.9, confidence_unavailable=False) == "已确认"
    assert field_review_status(0.5, confidence_unavailable=False) == "低置信度"
    assert field_review_status(None, confidence_unavailable=True) == "置信度未知"
    # 没有分数时不许伪装成「低置信度」——那会让人以为有个偏低的分数
    assert field_review_status(0.0, confidence_unavailable=True) == "置信度未知"


def test_边界值算已确认():
    assert field_review_status(0.70, confidence_unavailable=False) == "已确认"
    assert field_review_status(0.699, confidence_unavailable=False) == "低置信度"


def test_环境变量能覆盖(monkeypatch):
    monkeypatch.setenv("AICHECK_FIELD_CONFIRM_CONFIDENCE", "0.5")
    assert field_confirm_confidence() == 0.5
    assert field_review_status(0.6, confidence_unavailable=False) == "已确认"


def test_环境变量写坏时退回默认(monkeypatch):
    """一个写坏的环境变量不该把全站字段一律变成已确认或一律待核对。"""
    for bad in ("", "  ", "abc", "0", "-1", "2", "1.5"):
        monkeypatch.setenv("AICHECK_FIELD_CONFIRM_CONFIDENCE", bad)
        assert field_confirm_confidence() == DEFAULT_FIELD_CONFIRM_CONFIDENCE, bad


def test_不许再有硬写的阈值():
    """这条线只能有一份。

    改一处漏一处的后果是「字段标着已确认，却仍然挂在阻塞项里」，
    而没有任何东西会报错——所以用测试把散落的常量挡住。
    """
    offenders: list[str] = []
    for path in (
        BACKEND / "libs" / "db" / "repository.py",
        BACKEND / "apps" / "api" / "routes.py",
    ):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if "confidence" not in code.lower():
                continue
            # structureConfidence 是**表格结构**的可用度，不是字段置信度，
            # 两者本来就该是两条线。混进来只会逼着后人把无关的常量也搬走。
            if "structureconfidence" in code.lower():
                continue
            if re.search(r"[<>]=?\s*0\.\d+", code):
                offenders.append(f"{path.name}:{lineno} {line.strip()[:90]}")
    assert not offenders, "还有硬写的置信度阈值：\n" + "\n".join(offenders)
