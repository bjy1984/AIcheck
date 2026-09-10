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

# 2026-09-10 实测：交接记录 28 项 → 补 AC-R11-03 得 27 → 补 AC-R45-01 得 26
# → 补 AC-R64-01／AC-R66-01／AC-R67-01（泄漏试验一组）得 23
# → 补 AC-R63-01（柔性分析）／AC-R68-01（吹扫清洗）得 21
# → 补 AC-R47／R48／R50／R53／R54／R55-01（安装与布置一组，判据全部来自
#   GB/T 20801.1-2025 已逐句核对的正文）与 AC-R53-02（连接设备的管道）得 14 → 补 AC-R52-01（现场制作）得 13。
# R45 是第一条走通"判据冻结进规则包 + frozen_domain_checks 统一判定"这条路的通用解释器规则。
EXPECTED_UNCONFIGURED = 13
EXPECTED_RULES = {
    "R10", "R11", "R43", "R44", "R46", "R49", "R51",
    "R56", "R57", "R58",
}


def dedicated_handler_names() -> set[str]:
    """business_tools 里真正有实现的判定工具（handlers 映射的键）。"""
    from libs.review_tools import business_tools

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
    """只有 business_tools 在消费 ruleChecks，没有任何地方**产生**它。

    这决定了补齐方式：不是"往绑定里填几行 ruleChecks"，而是走 frozen_domain_checks
    那条路——判据冻结进规则包，事实侧按 actualPath 解析。R11-03 与 R45 已按此走通。

    这里只认"当成数据写出去"的用法（赋值或放进字典），注释与文档字符串里提到不算。
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    producers = []
    for path in list((root / "libs").rglob("*.py")) + list((root / "apps").rglob("*.py")):
        if path.name == "business_tools.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            written = isinstance(node, ast.Constant) and node.value == "ruleChecks"
            if written and not isinstance(getattr(node, "parent", None), ast.Expr):
                producers.append(str(path.relative_to(root)))
                break
    assert producers == [], f"出现了 ruleChecks 的产生方：{producers}；请同步更新本测试与补齐方案"
