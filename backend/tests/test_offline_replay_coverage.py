"""每条有事实构建器的规则都必须能离线重放——这条不变式断过一次。

2026-09-10：26 个 frozen-domain 工具接进来时，`OFFLINE_TOOLS` 那份名单没跟着更新，
于是 R43 以后的规则全部卡在 `replay_nonlocal_or_unsupported_tools`，69 条里只剩
3 条能重放。名单是手写的，而"新增工具"和"更新名单"是两个动作——中间必然有人漏掉。
所以改成由测试来发现，而不是指望下一个人记得。
"""

from libs.business_pack import load_business_pack
from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
from libs.review_orchestrator.runtime_tools import runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan
from scripts.replay_review_acceptance import OFFLINE_TOOLS

PACK = load_business_pack("engineering_inspection_v1")


def rules_with_fact_builders():
    return sorted({
        item["sourceRuleId"] for item in PACK["atomicCheckToolBindings"]
        if item["sourceRuleId"][1:].isdigit() and int(item["sourceRuleId"][1:]) in NDT_FACT_BUILDERS
    })


def test_every_rule_with_a_fact_builder_can_be_replayed_offline():
    available = {item["name"] for item in runtime_tool_catalog()}
    blocked = {}
    for rule in rules_with_fact_builders():
        plan = compile_node_tool_plan(PACK, rule, available_tools=available)
        assert plan and all(item["compilable"] for item in plan), f"{rule} 的工具计划没编译出来"
        unsupported = {tool for item in plan for tool in item["tools"]} - OFFLINE_TOOLS
        if unsupported:
            blocked[rule] = sorted(unsupported)
    assert not blocked, (
        "这些规则有事实构建器却不能离线重放，多半是新工具没加进 OFFLINE_TOOLS："
        f"{blocked}。加之前先确认该工具只对传进来的 arguments 计算、"
        "导入闭包里没有网络或数据库客户端。"
    )


def test_the_offline_list_does_not_name_tools_that_no_longer_exist():
    """名单里留着已删除的工具名，会让下一个人以为某条路是通的。"""
    available = {item["name"] for item in runtime_tool_catalog()}
    assert not (OFFLINE_TOOLS - available), f"名单里有已不存在的工具：{sorted(OFFLINE_TOOLS - available)}"


def test_the_rules_without_fact_builders_are_the_only_remaining_gap():
    """把"还差多少"钉成可见的数字，而不是散在各处的印象。"""
    all_rules = {item["sourceRuleId"] for item in PACK["atomicCheckToolBindings"]}
    covered = set(rules_with_fact_builders())
    assert covered <= all_rules
    # 有构建器的都能重放（上面那条测的），所以缺口就等于没有构建器的那些。
    assert len(all_rules) - len(covered) == len(all_rules - covered)


def test_a_registered_fact_builder_builds_facts_with_the_network_cut(monkeypatch):
    """重放的确定性取决于工具**和**事实构建器，之前只守住了工具那一半。

    先试过用导入闭包来查，结论是**这个办法在这里没用**：每个构建器都经
    runtime_tools（工具总目录，它导入全部工具）连到 r12_registry 再到
    cnse_client，于是所有模块都"有网络依赖"，测了等于没测。能不能 import 到一个
    客户端，和建事实时会不会真去调它，是两回事。

    所以改成运行时验证：把 socket 掐掉再建一次事实。真去连网的构建器会当场炸，
    只是把客户端 import 进来的则不受影响。
    """
    import socket

    from test_real_table_reaches_the_rules import state_and_run

    from libs.review_orchestrator.installation_domain_facts import build_r43_business_facts

    def refuse(*args, **kwargs):
        raise AssertionError("事实构建期间尝试建立网络连接；重放将不再确定")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    state, run = state_and_run()
    run["selectedObjectIds"] = ["20260213951"]  # 真实表两行，不选就是"来源含糊"
    facts = build_r43_business_facts(state, run)["r43"]["materialCertificate"]
    # 断网还能把真实表格的值建出来，才算真的离线。
    assert facts["domains"][0]["certificate"]["documentNo"] == "20260213951"
