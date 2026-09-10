"""落到通用解释器且未配 ruleChecks 的原子项——这些规则永远给不出结论。

背景：绑定里写着"专用工具名"（evaluate_corrosion_protection、evaluate_leak_test 等），
但 business_tools 的 handlers 里没有对应实现，最终落到 evaluate_rule_profile。
而它要求调用方同时给出 requiredFields 与 ruleChecks，两者都没配时直接返回
`requiredFields_not_configured` 的证据不足——资料再齐也判不出符合或不符合。

更深一层：**全仓没有任何地方产生 ruleChecks**，只有工具在消费它。也就是说这条
通用路径不是"暂时没配"，而是还没有配置它的机制。

这条测试把当前数字钉住，作用有两个：
- 补上一条就该减一，不允许悄悄增加；
- 发布门槛上不能拿"绑定已存在"冒充"判定已具备"。禁止只改 lifecycleStatus
  就宣称完成全量业务发布。
"""
import inspect

from libs.business_pack.loader import load_business_pack

# 2026-09-10 实测：27 项 / 23 条规则。R11-03 当日已补为专用判定，故比交接记录的 28 少一条。
EXPECTED_UNCONFIGURED = 27
EXPECTED_RULES = {
    "R10", "R11", "R43", "R44", "R45", "R46", "R47", "R48", "R49", "R50", "R51", "R52",
    "R53", "R54", "R55", "R56", "R57", "R58", "R63", "R64", "R66", "R67", "R68",
}


def dedicated_handler_names() -> set[str]:
    """business_tools 里真正有实现的判定工具（handlers 映射的键）。"""
    import libs.review_tools.business_tools as business_tools

    source = inspect.getsource(business_tools)
    start = source.index("handlers: dict[str, Callable")
    end = source.index("handler = handlers.get(tool_name)")
    return {line.split('"')[1] for line in source[start:end].split("\n") if '":' in line}


def unconfigured_generic_bindings():
    pack = load_business_pack()
    bindings = (pack.get("atomicCheckToolBindingSet") or {}).get("bindings") or pack.get("atomicCheckToolBindings") or []
    dedicated = dedicated_handler_names()
    rows = []
    for binding in bindings:
        judging = [tool for tool in binding.get("tools") or []
                   if tool.startswith(("evaluate_", "classify_", "resolve_"))]
        if not judging or any(tool in dedicated for tool in judging):
            continue
        if (binding.get("parameters") or {}).get("ruleChecks"):
            continue
        rows.append(binding)
    return rows


def test_generic_interpreter_bindings_are_counted_and_do_not_grow():
    rows = unconfigured_generic_bindings()
    assert len(rows) == EXPECTED_UNCONFIGURED, (
        f"落到通用解释器且未配 ruleChecks 的原子项数变了：{len(rows)}。"
        "补上判定就把 EXPECTED_UNCONFIGURED 减小；变多说明新绑定又只写了工具名。"
    )
    assert {row["sourceRuleId"] for row in rows} == EXPECTED_RULES


def test_the_generic_interpreter_cannot_conclude_without_configuration():
    """这些原子项无论资料多齐都只会返回证据不足——把这件事钉死，别当成"数据不足"。"""
    from libs.review_tools.business_tools import evaluate_rule_profile

    rows = unconfigured_generic_bindings()
    binding = rows[0]
    tool = next(tool for tool in binding["tools"] if tool.startswith("evaluate_"))
    rich_facts = {"facts": {path.split(".")[0]: {"anything": "值齐全"} for path in binding["requiredFacts"]}}
    output = evaluate_rule_profile(tool, {**binding["parameters"], **rich_facts})
    assert output["result"] == "evidence_insufficient"
    assert output["warnings"] == ["requiredFields_not_configured"], (
        "缺的是配置，不是资料——提示必须能把这两件事分开"
    )


def test_nothing_in_the_repository_produces_rule_checks_yet():
    """全仓只有工具消费 ruleChecks，没有任何地方产生它。

    这决定了补齐方式：不是"往绑定里填几行"，而是先要有产生 ruleChecks 的机制
    （像 R09/R11 那样把判据冻结进规则包，再由事实侧解析 actualPath）。
    """
    import pathlib
    import subprocess

    root = pathlib.Path(__file__).resolve().parents[1]
    hits = subprocess.run(["grep", "-rln", "--include=*.py", "ruleChecks", "libs", "apps"], cwd=root,
                          capture_output=True, text=True).stdout.split()
    producers = [path for path in hits if not path.endswith("business_tools.py")]
    assert producers == [], f"出现了 ruleChecks 的产生方：{producers}；请同步更新本测试与补齐方案"
