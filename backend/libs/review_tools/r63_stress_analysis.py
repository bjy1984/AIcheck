"""R63：管道系统的柔性（应力）分析——免除或替代压力试验的前置条件。

原先 AC-R63-01 绑的 evaluate_stress_analysis 在 business_tools 里没有实现，
落到通用解释器且 ruleChecks 无人产生——资料再齐也只返回"未配置"的证据不足。

判据取自规则包冻结的 `stressAnalysisRules`；判定语义共用
`frozen_domain_checks.evaluate_frozen_domains`，四种结果的边界在那个模块里统一定义。

一个容易出错的地方写在这里：8.6.1.7 是"同时满足 a) b) c) 三项才可免除压力试验"。
只核柔性分析这一项就宣布可以免除，正是把局部评估当成完整结论。所以
`exemption_requires_all_preconditions` 与 `coverage_includes_all_exempted_systems`
都在申请免除时才适用，且缺一不可；a)、c) 两项本身由 R35／R36 与 R64／R67 判定。
"""
from __future__ import annotations

from libs.review_tools.frozen_domain_checks import evaluate_frozen_domains, frozen_rules_for_rule

RULE_VERSION = "r63-flexibility-stress-analysis-v1"
SCOPE_FIELDS = ("projectId", "objectType", "objectId", "reportVersionId")


def evaluate_r63_stress_analysis(arguments):
    return evaluate_frozen_domains(
        "evaluate_r63_stress_analysis",
        arguments,
        rule_version=RULE_VERSION,
        scope_fields=SCOPE_FIELDS,
        version_field="reportVersionId",
        code_prefix="r63_stress",
    )


def frozen_stress_analysis_rules(run=None):
    """规则包 CLAUSE-PKG-R63 里冻结的 stressAnalysisRules。"""
    return frozen_rules_for_rule("R63", "stressAnalysisRules", run)
