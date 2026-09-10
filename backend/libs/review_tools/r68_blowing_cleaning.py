"""R68：管道清理、吹扫和清洗。

原先 AC-R68-01 绑的 evaluate_blowing_cleaning 在 business_tools 里没有实现，
落到通用解释器且 ruleChecks 无人产生——资料再齐也只返回"未配置"的证据不足。

判据取自规则包冻结的 `blowingCleaningRules`；判定语义共用
`frozen_domain_checks.evaluate_frozen_domains`，四种结果的边界在那个模块里统一定义。

吹洗方法（水冲洗、空气吹扫、蒸汽吹扫、化学清洗）各有各的条文要求，所以判据按
`medium.*` 的方法开关分支适用：不是这种方法就不适用，方法本身取不到值则保持
证据不足——不按"没写就是没做"，也不按"没写就放过"。
"""
from __future__ import annotations

from libs.review_tools.frozen_domain_checks import evaluate_frozen_domains, frozen_rules_for_rule

RULE_VERSION = "r68-blowing-and-cleaning-v1"
SCOPE_FIELDS = ("projectId", "objectType", "objectId", "recordVersionId")


def evaluate_r68_blowing_cleaning(arguments):
    return evaluate_frozen_domains(
        "evaluate_r68_blowing_cleaning",
        arguments,
        rule_version=RULE_VERSION,
        scope_fields=SCOPE_FIELDS,
        version_field="recordVersionId",
        code_prefix="r68_blowing",
    )


def frozen_blowing_cleaning_rules(run=None):
    """规则包 CLAUSE-PKG-R68 里冻结的 blowingCleaningRules。"""
    return frozen_rules_for_rule("R68", "blowingCleaningRules", run)
