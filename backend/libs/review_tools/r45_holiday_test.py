"""R45：防腐层电火花检测（漏点检测）。

原先 AC-R45-01 绑的 evaluate_corrosion_protection 在 business_tools 里没有实现，
落到通用解释器，而它要的 ruleChecks 全仓没人产生——资料再齐也只返回
`requiredFields_not_configured` 的证据不足。

判据取自规则包冻结的 `holidayTestRules`；判定语义与 R11-03 共用
`frozen_domain_checks.evaluate_frozen_domains`，四种结果的边界在那个模块里统一定义。
"""
from __future__ import annotations

from libs.review_tools.frozen_domain_checks import evaluate_frozen_domains, frozen_rules_for_rule

RULE_VERSION = "r45-coating-holiday-test-v1"
SCOPE_FIELDS = ("projectId", "objectType", "objectId", "recordVersionId")


def evaluate_r45_holiday_test(arguments):
    return evaluate_frozen_domains(
        "evaluate_r45_holiday_test",
        arguments,
        rule_version=RULE_VERSION,
        scope_fields=SCOPE_FIELDS,
        version_field="recordVersionId",
        code_prefix="r45_holiday",
    )


def frozen_holiday_test_rules(run=None):
    """规则包 CLAUSE-PKG-R45 里冻结的 holidayTestRules。"""
    return frozen_rules_for_rule("R45", "holidayTestRules", run)
