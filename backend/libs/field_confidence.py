"""字段置信度的判定口径——**唯一一份**。

## 为什么单独成文件

这条线原先硬写在两个地方：

    libs/db/repository.py   confidence >= 0.85 -> 已确认，否则低置信度
    apps/api/routes.py      confidence < 0.85  -> 进阻塞项清单

同一条规则写在两处，改一处就会出现「字段标着已确认，却仍然挂在阻塞项里」
——两个界面各说各的，而没有任何东西会报错。这个形态在本仓库反复出现。

## 0.85 太高了

用户反馈「把置信度调低」。0.85 对 OCR 来说是很严的线：常规印刷体
PaddleOCR 大多落在 0.75~0.95，稍有噪点就掉到 0.8 以下，于是**几乎每个字段
后面都跟着「需回原文核对」**。提示到处都是，就等于没有提示——
真正该被核对的那几个反而淹没了。

降到 0.70。

## 但降阈值不等于放松把关

阈值管的是「要不要提醒人来看一眼」，不是「这个值对不对」。
值本身对不对由抽取环节的护栏负责（例如许可范围必须含真实许可项目，
见 apps/ocr_service/service.py 的 license_scope_text_is_usable）。
**这两件事不能混为一谈**：把阈值调低来「减少报警」，同时又指望它拦住错值，
两头都会落空。

可以用 AICHECK_FIELD_CONFIRM_CONFIDENCE 覆盖，便于按现场数据调。
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_FIELD_CONFIRM_CONFIDENCE = 0.70


def field_confirm_confidence() -> float:
    """达到这个分数就算「已确认」，不再提示人工核对。

    读不出来或超出 (0, 1] 时退回默认值——一个写坏的环境变量不该
    把全站字段一律变成「已确认」或一律变成「待核对」。
    """
    raw = os.getenv("AICHECK_FIELD_CONFIRM_CONFIDENCE")
    if raw is None or not str(raw).strip():
        return DEFAULT_FIELD_CONFIRM_CONFIDENCE
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_FIELD_CONFIRM_CONFIDENCE
    if not 0 < value <= 1:
        return DEFAULT_FIELD_CONFIRM_CONFIDENCE
    return value


def is_low_confidence(confidence: Any) -> bool:
    """这个分数低不低。

    调用点很多（阻塞项、统计、质量报告…），每处都写一遍
    `float(x.get("confidence") or 0) < 阈值` 的话，阈值就会再次散开——
    这正是这次要收的东西。给一个能直接用在推导式里的判断。
    """
    try:
        value = float(confidence if confidence is not None else 0)
    except (TypeError, ValueError):
        value = 0.0
    return value < field_confirm_confidence()


def field_review_status(confidence: float | None, *, confidence_unavailable: bool) -> str:
    """字段的复核状态。

    三态要分开，处置方式不同：
      已确认     —— 分数够高，不用管
      置信度未知 —— 引擎压根没给分（MinerU 的 VLM 通道逐片不给分），
                    可信度无从判断，得回原文看
      低置信度   —— 引擎给了分但不高，核对字面值即可

    把后两者合并成一个的话，监检看到「低置信度」会以为有个分数偏低，
    实际上根本没有分数——那是两种不同的不确定。
    """
    if confidence_unavailable:
        return "置信度未知"
    if float(confidence or 0) >= field_confirm_confidence():
        return "已确认"
    return "低置信度"
