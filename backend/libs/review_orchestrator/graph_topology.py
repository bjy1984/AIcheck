"""审查编排图的静态拓扑：步骤及其顺序。

从 execution.py 搬出来的纯声明数据。步骤定义与执行逻辑放在一起没有好处——
这份表被 deployment_report、import_layering 等多处引用，读它的人不该被迫
翻四千行的执行文件。

`taskQueue` 决定每步派往哪个 worker 队列，是部署拓扑的一部分：
review.llm 要能连模型，review.retrieval 要能连向量库，review.graph/validation
只吃 CPU。改这里等于改部署要求。
"""

from __future__ import annotations

from typing import Any

REVIEW_GRAPH_STEPS: list[dict[str, Any]] = [
    {"key": "classify_ocr_tables", "label": "插件·Jev 表格行分类（可选，未选用则略过）", "taskQueue": "review.llm"},
    {"key": "load_context", "label": "加载项目上下文", "taskQueue": "review.graph"},
    {"key": "load_ocr_result", "label": "加载 OCR 证据", "taskQueue": "review.graph"},
    {"key": "run_rule_engine", "label": "执行确定性规则", "taskQueue": "review.validation"},
    # 键名保留兼容部署报告；题目已改为按原子项指令的固定模板生成，不再调 Qwen。
    {"key": "qwen_compose_jev_questions", "label": "插件·Jev 按冻结模板准备语义题（可选）", "taskQueue": "review.llm"},
    {"key": "jev_decision", "label": "插件·Jev 分歧提示与事实核对（可选，不改结论）", "taskQueue": "review.llm"},
    {"key": "retrieve_knowledge", "label": "检索知识依据", "taskQueue": "review.retrieval"},
    {"key": "build_prompt", "label": "构造审查 Prompt", "taskQueue": "review.graph"},
    {"key": "llm_generate_findings", "label": "QwenRuntime 生成审查草稿", "taskQueue": "review.llm"},
    {"key": "schema_validation", "label": "Schema 校验", "taskQueue": "review.validation"},
    {"key": "evidence_validation", "label": "证据校验", "taskQueue": "review.validation"},
    {"key": "reference_validation", "label": "依据校验", "taskQueue": "review.validation"},
    {"key": "critic_review", "label": "Critic 复核", "taskQueue": "review.llm"},
    {"key": "quality_gate", "label": "质量门禁", "taskQueue": "review.validation"},
    {"key": "persist_drafts", "label": "持久化草稿", "taskQueue": "review.graph"},
]

# 当前是纯线性链路，边由步骤顺序推导，避免两处各写一份再对不上。
REVIEW_GRAPH_EDGES: list[dict[str, str]] = [
    {"source": REVIEW_GRAPH_STEPS[index]["key"], "target": REVIEW_GRAPH_STEPS[index + 1]["key"]}
    for index in range(len(REVIEW_GRAPH_STEPS) - 1)
]
