"""Node-specific NDT fact builders; registration does not publish rule bindings."""
from libs.review_orchestrator.installation_domain_facts import (
    build_r10_business_facts,
    build_r43_business_facts,
    build_r44_business_facts,
    build_r46_business_facts,
    build_r56_business_facts,
    build_r57_business_facts,
    build_r58_business_facts,
    build_r47_business_facts,
    build_r48_business_facts,
    build_r49_business_facts,
    build_r50_business_facts,
    build_r52_business_facts,
    build_r53_business_facts,
    build_r54_business_facts,
    build_r55_business_facts,
)
from libs.review_orchestrator.leak_test_facts import (
    build_r64_business_facts,
    build_r66_business_facts,
    build_r67_business_facts,
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
                     57: build_r57_business_facts, 58: build_r58_business_facts}
