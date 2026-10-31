"""使用教程检索：教程文件的结构约束，加上一组「用户会怎么问 → 该翻到哪一节」的回归问答。

问答集是这套功能真正的验收：教程改版、检索打分调整之后，最容易悄悄坏掉的就是
“用户问得很自然，却翻不到该翻的那一节”。每一条写的是用户实际会用的说法，不是小节标题。
"""

from __future__ import annotations

import pytest

from libs import help_center


def test_教程文件按二级标题切成小节且每节有正文():
    sections = help_center.load_sections()
    assert len(sections) >= 20
    assert all(section.body.strip() for section in sections)
    # 同一份文档里标题不能重复，否则引用“出自哪一节”会指不清
    seen = {(section.doc_id, section.heading) for section in sections}
    assert len(seen) == len(sections)


def test_下划线开头的维护说明不进检索():
    assert all(not section.doc_id.startswith("_") for section in help_center.load_sections())


def test_小节长度在可读范围内():
    """超长小节多半是写法问题（一节里塞了好几件事），也会被截断后丢信息。"""
    too_long = [s.path_label for s in help_center.load_sections() if len(s.body) > help_center.MAX_SECTION_CHARS]
    assert not too_long, too_long


# 用户的自然问法 → 应出现在前三条结果里的小节标题片段
QA_SET = [
    ("怎么退回补正", "退回补正"),
    ("保存不了满足要求怎么办", "保存不了"),
    ("OCR 抽取不完整是什么意思", "OCR"),
    ("AI审查按钮在哪里", "AI审查助手在哪里"),
    ("怎么关闭AI助手面板", "AI审查助手在哪里"),
    ("一键分析是干什么的", "顶部按钮"),
    ("自动审查要不要开", "自动审查是什么"),
    ("待审查和未补正有什么区别", "节点旁边的标签"),
    ("怎么切换项目", "怎么切换项目"),
    ("总览页N项需要你处理是什么意思", "项目总览页"),
    ("我是新来的不知道先做什么", "我该先做什么"),
    ("R69怎么处理", "R69"),
    ("查看原文怎么打开", "怎么查看资料原文"),
    ("置信度是什么", "证据定位弹窗"),
    ("怎么上传现场照片", "上传监检自己形成的证据"),
    ("证据不足和需补正有什么区别", "需补正和证据不足"),
    ("重要节点审查怎么用", "重要节点审查"),
    ("待办消息里的完成是什么", "顶部按钮"),
    ("PDF 打不开", "证据定位弹窗"),
    ("为什么我看不到某个节点", "看不到某个节点"),
    ("斜杠命令有哪些", "怎么向助手提问"),
    ("助手能不能帮我保存结论", "助手能做什么"),
]


@pytest.mark.parametrize(("question", "expected"), QA_SET)
def test_自然问法能翻到该翻的小节(question: str, expected: str):
    headings = [item["heading"] for item in help_center.search_help_sections(question)]
    assert any(expected in heading for heading in headings), (question, headings)


@pytest.mark.parametrize("question", ["今天天气怎么样", "怎么做红烧肉", "", "   ", "？！"])
def test_与系统无关的问题不返回教程(question: str):
    assert help_center.search_help_sections(question) == []


def test_角色隔离_监检教程不给别的角色():
    assert help_center.search_help_sections("怎么退回补正", role="contractor") == []
    assert help_center.search_help_sections("怎么退回补正", role="inspection")


def test_最多返回三节且按相关度排序():
    results = help_center.search_help_sections("审查结论 证据 补正")
    assert 1 <= len(results) <= 3
    scores = [item["score"] for item in results]
    assert scores == sorted(scores, reverse=True)


def test_工具命中时要求只依据教程作答():
    output = help_center.search_help_docs_tool({"query": "怎么退回补正"})
    assert output["status"] == "succeeded"
    assert output["sectionCount"] == len(output["sections"]) >= 1
    assert "出自哪一节" in output["note"]
    assert all(item["source"].startswith("《") for item in output["sections"])


def test_工具没命中时明说教程里没有且不让编():
    output = help_center.search_help_docs_tool({"query": "怎么做红烧肉"})
    assert output["status"] == "succeeded"
    assert output["sectionCount"] == 0
    assert "不要编造" in output["note"]


def test_工具缺参数时拒绝():
    assert help_center.search_help_docs_tool({})["status"] == "rejected"
    assert help_center.search_help_docs_tool(None)["status"] == "rejected"


def test_工具已注册给对话_agent_并能被分发():
    from apps.api import routes

    names = {item["function"]["name"] for item in routes.REVIEW_CONVERSATION_AGENT_TOOLS}
    assert help_center.TOOL_NAME in names

    output = routes.review_conversation_agent_tool_output(
        help_center.TOOL_NAME,
        {"query": "怎么退回补正"},
        session={},
        project={},
        node={},
        basis={},
        basis_items=[],
        readiness={},
        evidence_links=[],
        review_run=None,
    )
    assert output["sectionCount"] >= 1
    assert "使用教程" in routes.review_conversation_tool_result_summary(help_center.TOOL_NAME, output)
