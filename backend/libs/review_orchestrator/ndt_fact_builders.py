"""Node-specific NDT fact builders; registration does not publish rule bindings."""
from libs.review_orchestrator.r35_facts import build_r35_business_facts
from libs.review_orchestrator.r36_facts import build_r36_business_facts
from libs.review_orchestrator.r37_facts import build_r37_business_facts

NDT_FACT_BUILDERS = {35: build_r35_business_facts, 36: build_r36_business_facts, 37: build_r37_business_facts}
