"""R11-03：施工方案里的焊接、试验内容是否满足施工标准要求。

原先 AC-R11-03 只绑通用的 evaluate_construction_plan，等于没有专用判定。判据取自
规则包冻结的 `constructionPlanProcessRules`——工具自己不推导限值，也不猜适用性。

与 R09 的关系：R09 问"设计文件有没有写、写得够不够"，这里问"施工方案有没有把它落下来"。
数值判据同源（同一批冻结值）。

判定语义与其余按冻结判据核对的规则共用 `frozen_domain_checks.evaluate_frozen_domains`，
四种结果的边界写在那个模块的文档里，不允许各规则各自解释。
"""
from __future__ import annotations

from libs.review_tools.frozen_domain_checks import evaluate_frozen_domains, frozen_rules_for_rule

RULE_VERSION = "r11-construction-plan-process-standards-v1"
SCOPE_FIELDS = ("projectId", "objectType", "objectId", "planVersionId")


def evaluate_r11_process_standards(arguments):
    return evaluate_frozen_domains(
        "evaluate_r11_process_standards",
        arguments,
        rule_version=RULE_VERSION,
        scope_fields=SCOPE_FIELDS,
        version_field="planVersionId",
        code_prefix="r11_process",
    )


def frozen_construction_plan_process_rules(run=None):
    """规则包 CLAUSE-PKG-R11 里冻结的 constructionPlanProcessRules。"""
    return frozen_rules_for_rule("R11", "constructionPlanProcessRules", run)
