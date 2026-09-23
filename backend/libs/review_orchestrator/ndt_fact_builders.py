"""Node-specific NDT fact builders; registration does not publish rule bindings."""
from libs.review_orchestrator.installation_domain_facts import (
    build_r10_business_facts,
    build_r43_business_facts,
    build_r44_business_facts,
    build_r46_business_facts,
    build_r47_business_facts,
    build_r48_business_facts,
    build_r49_business_facts,
    build_r50_business_facts,
    build_r52_business_facts,
    build_r53_business_facts,
    build_r54_business_facts,
    build_r55_business_facts,
    build_r56_business_facts,
    build_r57_business_facts,
    build_r58_business_facts,
)
from libs.review_orchestrator.leak_test_facts import (
    build_r64_business_facts,
    build_r66_business_facts,
    build_r67_business_facts,
)
from libs.review_orchestrator.r11_facts import build_r11_business_facts
from libs.review_orchestrator.r13_facts import build_r13_business_facts
from libs.review_orchestrator.r14_facts import build_r14_business_facts
from libs.review_orchestrator.r15_facts import build_r15_business_facts
from libs.review_orchestrator.r16_facts import build_r16_business_facts
from libs.review_orchestrator.r17_facts import build_r17_business_facts
from libs.review_orchestrator.r18_facts import build_r18_business_facts
from libs.review_orchestrator.r20_r23_facts import (
    build_r20_business_facts,
    build_r21_business_facts,
    build_r22_business_facts,
    build_r23_business_facts,
)
from libs.review_orchestrator.r24_r34_facts import (
    build_r25_business_facts,
    build_r26_business_facts,
    build_r27_business_facts,
    build_r28_business_facts,
    build_r29_business_facts,
    build_r30_business_facts,
    build_r31_business_facts,
    build_r32_business_facts,
    build_r33_business_facts,
    build_r34_business_facts,
)
from libs.review_orchestrator.r35_facts import build_r35_business_facts
from libs.review_orchestrator.r36_facts import build_r36_business_facts
from libs.review_orchestrator.r37_facts import build_r37_business_facts
from libs.review_orchestrator.r39_facts import build_r39_business_facts
from libs.review_orchestrator.r40_facts import build_r40_business_facts
from libs.review_orchestrator.r45_facts import build_r45_business_facts
from libs.review_orchestrator.r63_r68_facts import (
    build_r63_business_facts,
    build_r68_business_facts,
)

NDT_FACT_BUILDERS = {35: build_r35_business_facts, 36: build_r36_business_facts, 37: build_r37_business_facts, 39: build_r39_business_facts, 40: build_r40_business_facts,
                     45: build_r45_business_facts,
                     64: build_r64_business_facts, 66: build_r66_business_facts,
                     67: build_r67_business_facts,
                     63: build_r63_business_facts, 68: build_r68_business_facts,
                     10: build_r10_business_facts,
                     43: build_r43_business_facts, 44: build_r44_business_facts,
                     46: build_r46_business_facts,
                     47: build_r47_business_facts, 48: build_r48_business_facts,
                     49: build_r49_business_facts,
                     50: build_r50_business_facts, 52: build_r52_business_facts,
                     53: build_r53_business_facts,
                     54: build_r54_business_facts, 55: build_r55_business_facts,
                     56: build_r56_business_facts,
                     57: build_r57_business_facts, 58: build_r58_business_facts,
                     # 这些构建器一直存在，只是登记在 execution.py 的主管线分派里，
                     # 没进这份**重放**登记本，于是那些规则一直不可重放。
                     # 2026-09-10 掐网跑它们各自的测试（96 条）确认建事实期间不连网：
                     # 导入链上确实经 runtime_tools 够得着外部登记查询的客户端，
                     # 但够得着和会去调是两回事，前者不构成不可重放。
                     11: build_r11_business_facts,
                     13: build_r13_business_facts, 14: build_r14_business_facts,
                     15: build_r15_business_facts, 16: build_r16_business_facts,
                     17: build_r17_business_facts, 18: build_r18_business_facts,
                     20: build_r20_business_facts, 21: build_r21_business_facts,
                     22: build_r22_business_facts, 23: build_r23_business_facts,
                     # R24 不在此列：它的 AC-R24-01 走 verify_welder_on_platform，
                     # 那个工具会去查特种设备公示平台（search_cnse_persons_tool），
                     # 是真的连网，重放时会跟着去查，同一份 fixture 结果就不再固定。
                     25: build_r25_business_facts,
                     26: build_r26_business_facts, 27: build_r27_business_facts,
                     28: build_r28_business_facts, 29: build_r29_business_facts,
                     30: build_r30_business_facts, 31: build_r31_business_facts,
                     32: build_r32_business_facts, 33: build_r33_business_facts,
                     34: build_r34_business_facts}
