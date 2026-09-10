"""R64／R66／R67：泄漏试验的替代性、条件与方法报告。

这三条原先都绑 evaluate_leak_test，而那个名字在 business_tools 里没有实现，
落到通用解释器且 ruleChecks 无人产生——资料再齐也只返回"未配置"的证据不足。

判据取自各自规则包冻结的块；判定语义共用 frozen_domain_checks.evaluate_frozen_domains，
四种结果的边界在那个模块里统一定义。
"""
from __future__ import annotations

from libs.review_tools.frozen_domain_checks import evaluate_frozen_domains, frozen_rules_for_rule

SCOPE_FIELDS = ("projectId", "objectType", "objectId", "recordVersionId")

_SPECS = {
    "evaluate_r64_alternative_test": ("R64", "alternativeTestRules", "r64-alternative-test-v1", "r64_alternative"),
    "evaluate_r66_leak_test_conditions": ("R66", "leakTestConditionRules", "r66-leak-test-conditions-v1", "r66_leak_conditions"),
    "evaluate_r67_leak_test_method": ("R67", "leakTestMethodRules", "r67-leak-test-method-v1", "r67_leak_method"),
}


def _run(tool_name, arguments):
    _rule_id, _key, rule_version, prefix = _SPECS[tool_name]
    return evaluate_frozen_domains(tool_name, arguments, rule_version=rule_version,
                                   scope_fields=SCOPE_FIELDS, version_field="recordVersionId",
                                   code_prefix=prefix)


def evaluate_r64_alternative_test(arguments):
    return _run("evaluate_r64_alternative_test", arguments)


def evaluate_r66_leak_test_conditions(arguments):
    return _run("evaluate_r66_leak_test_conditions", arguments)


def evaluate_r67_leak_test_method(arguments):
    return _run("evaluate_r67_leak_test_method", arguments)


def frozen_leak_rules(tool_name, run=None):
    rule_id, key, _version, _prefix = _SPECS[tool_name]
    return frozen_rules_for_rule(rule_id, key, run)
