"""节点号 → 业务事实构建器的共享映射（不含依赖人工输入的 R12/R19 agent 型节点）。

execution.load_context 与对话正式判定（routes）各自维护过一份同样的表，改一处漏一处。
证书类节点（1/2/3/24/38）由 certificate_facts.with_certificate_fact_builders 在这份表上再套一层。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .r13_facts import build_r13_business_facts
from .r14_facts import build_r14_business_facts
from .r15_facts import build_r15_business_facts
from .r16_facts import build_r16_business_facts
from .r17_facts import build_r17_business_facts
from .r18_facts import build_r18_business_facts
from .r20_r23_facts import (
    build_r20_business_facts,
    build_r21_business_facts,
    build_r22_business_facts,
    build_r23_business_facts,
)
from .r24_r34_facts import BUILDERS as R24_R34_FACT_BUILDERS

NODE_FACT_BUILDERS: dict[int, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    13: build_r13_business_facts,
    14: build_r14_business_facts,
    15: build_r15_business_facts,
    16: build_r16_business_facts,
    17: build_r17_business_facts,
    18: build_r18_business_facts,
    20: build_r20_business_facts,
    21: build_r21_business_facts,
    22: build_r22_business_facts,
    23: build_r23_business_facts,
    **{int(key.removeprefix("r")): builder for key, builder in R24_R34_FACT_BUILDERS.items()},
}
