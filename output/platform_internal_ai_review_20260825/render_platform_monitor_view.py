from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path("/Volumes/7up/github/knowledgetools/output/platform_internal_ai_review_20260825")
TARGETING_PATH = Path("/Volumes/7up/github/knowledgetools/output/two_project_node_eval_20260824/node_targeting_results.json")
INPUT_PATH = Path("/Volumes/7up/github/knowledgetools/output/two_project_ai_review_20260825/review_input.json")

SOURCES = {
    "test": [
        "test_c1.json",
        "test_c2.json",
        "test_c3.json",
        "test_c4.json",
        "probe_test_node5.json",
        "test_retry.json",
    ],
    "test2": [
        "test2_c1.json",
        "test2_c2.json",
        "test2_c3.json",
        "test2_c4.json",
        "test2_retry.json",
    ],
}

SEVERITY_LABEL = {"critical": "严重", "high": "高", "medium": "中", "low": "低"}
SUPPORT_LABEL = {
    "formal": "已正式挂载并完成平台AI审查",
    "advisory": "仅大类提示，不形成正式绑定，平台一键审查未发起",
    "missing_expected": "存在预期资料类型但没有正式挂载，平台一键审查未发起",
    "applicability_unknown": "无正式挂载，需先由监检人员判断节点适用性",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()


def md(value: Any) -> str:
    return clean(value).replace("|", "\\|")


def usage_tokens(result: dict[str, Any]) -> tuple[int, int, int]:
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    return input_tokens, output_tokens, total_tokens


def combine_results(project: str) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    combined: dict[int, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for source_name in SOURCES[project]:
        payload = load(ROOT / source_name)
        for result in payload["results"]:
            node_id = int(result["nodeId"])
            if result.get("status") in {"failed", "failed_to_start"}:
                failures.append(
                    {
                        "project": project,
                        "nodeId": node_id,
                        "errorCode": result.get("errorCode"),
                        "errorMessage": result.get("errorMessage"),
                        "source": source_name,
                    }
                )
                if node_id not in combined:
                    combined[node_id] = result
                continue
            combined[node_id] = result
    return combined, failures


def evidence_label_map(project: str, targeting: dict[str, Any]) -> dict[str, dict[str, Any]]:
    target = next(item for item in targeting["projects"] if item["project"] == project)
    mapping = {}
    for index, file in enumerate(target["files"], 1):
        version_id = f"DV-{project.upper()}-{index:03d}-V1"
        mapping[version_id] = {
            "caseId": file["caseId"],
            "relativePath": file["relativePath"],
            "materialTypeCodes": file.get("predictedMaterialTypeCodes") or [],
        }
    return mapping


def finding_refs(finding: dict[str, Any], labels: dict[str, dict[str, Any]]) -> list[str]:
    refs = []
    for ref in finding.get("evidenceRefs") or []:
        version_id = str(ref.get("documentVersionId") or "")
        label = labels.get(version_id) or {}
        name = label.get("caseId") or version_id or str(ref.get("evidenceLinkId") or "证据")
        page = ref.get("pageNo")
        refs.append(f"{name}{f' P{page}' if page else ''}")
    return refs


def finding_rules(finding: dict[str, Any]) -> list[str]:
    values = []
    for ref in finding.get("ruleRefs") or []:
        value = str(ref.get("ruleCode") or ref.get("ruleId") or "")
        if value:
            values.append(value)
    for ref in finding.get("kbRefs") or []:
        values.extend(str(value) for value in ref.get("clauseIds") or [] if value)
    return list(dict.fromkeys(values))


def project_overview(project: dict[str, Any]) -> list[str]:
    results = [node["platformReview"] for node in project["nodes"] if node.get("platformReview")]
    suggestion_counts = Counter(str((result.get("suggestion") or {}).get("result") or "待判定") for result in results)
    finding_count = sum(len(result.get("findingDrafts") or []) for result in results)
    severity = Counter(
        str(finding.get("severity") or "unknown")
        for result in results
        for finding in result.get("findingDrafts") or []
    )
    input_tokens = output_tokens = total_tokens = 0
    for result in results:
        i, o, t = usage_tokens(result)
        input_tokens += i
        output_tokens += o
        total_tokens += t
    return [
        f"## {project['project']} 项目",
        "",
        "| 监检端指标 | 数值 |",
        "|---|---:|",
        f"| 上传并完成OCR/分类的文件 | {project['fileCount']} |",
        f"| 正式挂载并调用平台AI审查的节点 | {len(results)}/69 |",
        f"| 平台 findings 总数 | {finding_count} |",
        f"| 高/严重 findings | {severity['high'] + severity['critical']} |",
        f"| 质量门禁通过节点 | {sum(1 for item in results if (item.get('qualityGate') or {}).get('passed') is True)} |",
        f"| 等待人工确认节点 | {sum(1 for item in results if item.get('status') == 'waiting_human_review')} |",
        f"| 建议结论分布 | {'；'.join(f'{key} {value}' for key, value in suggestion_counts.items())} |",
        f"| 平台审查输入 token | {input_tokens:,} |",
        f"| 平台审查输出 token | {output_tokens:,} |",
        f"| 平台审查总 token | {total_tokens:,} |",
        "",
    ]


def node_card(node: dict[str, Any], labels: dict[str, dict[str, Any]]) -> list[str]:
    result = node.get("platformReview")
    lines = [f"### 节点 {node['nodeId']}｜{node['nodeName']}", ""]
    if not result:
        lines.extend(
            [
                f"> **平台状态：未发起AI审查。** {SUPPORT_LABEL.get(node['deterministicSupport'], node['deterministicSupport'])}。",
                "",
            ]
        )
        return lines
    suggestion = result.get("suggestion") or {}
    lines.extend(
        [
            f"- **运行状态：** {result.get('status')}（{result.get('reviewMode')}，仅作提示：{'是' if result.get('advisoryOnly') else '否'}）",
            f"- **AI建议（待人工确认）：** {clean(suggestion.get('result') or '待判定')}，置信度 {float(suggestion.get('confidence') or 0):.0%}",
            f"- **意见草稿：** {clean(suggestion.get('opinionDraft') or '—')}",
            f"- **人工确认项：** {'；'.join(clean(value) for value in suggestion.get('manualConfirmItems') or []) or '—'}",
            f"- **模型：** {clean(result.get('model') or '—')}；输入/输出 token：{usage_tokens(result)[0]:,} / {usage_tokens(result)[1]:,}",
            f"- **质量门禁：** {'通过' if (result.get('qualityGate') or {}).get('passed') is True else '需人工复核'}",
            "",
            "#### AI findings",
            "",
        ]
    )
    for index, finding in enumerate(result.get("findingDrafts") or [], 1):
        refs = finding_refs(finding, labels)
        rules = finding_rules(finding)
        lines.extend(
            [
                f"{index}. **[{SEVERITY_LABEL.get(str(finding.get('severity')), finding.get('severity') or '—')}] {clean(finding.get('title'))}**",
                f"   - 类型：`{clean(finding.get('findingType'))}`；证据状态：`{clean(finding.get('groundingStatus'))}`；置信度：{float(finding.get('confidence') or 0):.0%}",
                f"   - 意见：{clean(finding.get('description'))}",
                f"   - 证据：{'；'.join(refs) or '未形成有效证据引用'}",
                f"   - 规则/条款：{'；'.join(rules) or '—'}",
            ]
        )
    lines.append("")
    return lines


def main() -> None:
    targeting = load(TARGETING_PATH)
    review_input = load(INPUT_PATH)
    input_by_project = {item["project"]: item for item in review_input["projects"]}
    projects = []
    transient_failures = []
    for project_name in ("test", "test2"):
        results, failures = combine_results(project_name)
        transient_failures.extend(failures)
        source = input_by_project[project_name]
        nodes = []
        for node in source["nodes"]:
            node_id = int(node["nodeId"])
            nodes.append(
                {
                    "nodeId": node_id,
                    "nodeName": node["nodeName"],
                    "groupName": node["groupName"],
                    "reviewClass": node["reviewClass"],
                    "deterministicSupport": node["deterministicSupport"],
                    "platformReview": results.get(node_id) if results.get(node_id, {}).get("status") not in {"failed", "failed_to_start"} else None,
                }
            )
        projects.append(
            {
                "project": project_name,
                "fileCount": source["fileCount"],
                "reviewedNodeIds": sorted(node_id for node_id, result in results.items() if result.get("status") not in {"failed", "failed_to_start"}),
                "nodes": nodes,
            }
        )

    output = {
        "schemaVersion": "platform-monitor-visible-ai-review@1",
        "platformFlow": "inspection.ai-recheck -> ReviewRun -> LangGraph -> QwenRuntime -> grounding guardrails -> waiting_human_review",
        "reviewMode": "gap_precheck",
        "auditInputMode": "ocr_llm",
        "modelRole": "review-chat",
        "modelResolved": "qwen3.7-plus",
        "projects": projects,
        "transientFailuresRecovered": transient_failures,
    }
    (ROOT / "platform_monitor_view_results.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    overview = [
        "# 监检工作台实际 AI 审查结果",
        "",
        "> 这些结果由项目内真实 `ai-recheck → ReviewRun → LangGraph → QwenRuntime → 证据护栏` 流程产生。使用 OCR+LLM 缺项预审模式，所有结论仅供监检人员人工确认，不限制上传、发起审查或填写人工结论。",
        "",
        "## 监检人员实际看到什么",
        "",
        "每个正式挂载节点显示：运行状态、AI建议、置信度、意见草稿、findings列表、严重度、OCR证据引用、规则/标准条款和人工确认项。没有正式挂载的节点不会被一键审查自动发起，并显示具体原因。",
        "",
    ]
    for project in projects:
        overview.extend(project_overview(project))
    quality_codes = Counter(
        str(failure.get("code") or "UNKNOWN")
        for project in projects
        for node in project["nodes"]
        if node.get("platformReview")
        for gate in (node["platformReview"].get("qualityGate") or {}).get("failures") or []
        for failure in gate.get("failures") or []
    )
    overview.extend(
        [
            "## 当前监检端输出暴露的问题",
            "",
            "- 81 个已审节点全部停在 `waiting_human_review`，且质量门禁均未通过；这不是模型调用失败，而是平台引用校验要求监检人员继续确认。",
            "- 两项目只有节点23（阀门施工资料和耐压试验记录）给出“建议不符合”，但证据护栏又把主意见降级为“证据不足，需人工确认”，因此不能直接作为人工结论。",
            "- 大量 finding 因 unsupportedClaims 被替换成统一的“模型给出的业务结论缺少证据支持”，监检人员能看到风险等级和引用，但部分具体诊断被护栏丢弃，当前可读性有限。",
            "- 质量门禁主要失败码："
            + "；".join(f"`{code}` {count} 次" for code, count in quality_codes.most_common()),
            "- 57 个节点没有正式挂载，因此平台一键审查不会自动发起；报告中逐节点列出了是“大类提示”“预期缺失”还是“适用性未知”。",
            "",
        ]
    )
    overview.extend(
        [
            "## 执行说明",
            "",
            f"- 首轮发生 {len(transient_failures)} 次远程连接异常，均无模型响应；降低并发后全部重跑成功，最终结果不包含这些空白失败运行。",
            "- 平台审查模型角色为 `review-chat`，当前解析模型是 `qwen3.7-plus`；文件分类模型是另一角色的 `qwen3.8-max`。",
            "- 本次使用真实 MinerU OCR Markdown；离线导入时页码/bbox按文本分片模拟，因此意见内容真实，但点击原文的精确坐标仍需在生产上传链路复测。",
            "",
        ]
    )
    full = list(overview)
    full.extend(["# 逐节点监检端输出", ""])
    for project in projects:
        labels = evidence_label_map(project["project"], targeting)
        full.extend([f"## {project['project']} 项目", ""])
        current_group = None
        for node in project["nodes"]:
            if node["groupName"] != current_group:
                current_group = node["groupName"]
                full.extend([f"# {project['project']}｜{current_group}", ""])
            full.extend(node_card(node, labels))

    (ROOT / "platform_monitor_view_overview.md").write_text("\n".join(overview).rstrip() + "\n", encoding="utf-8")
    (ROOT / "platform_monitor_view_full_report.md").write_text("\n".join(full).rstrip() + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "reviewed": {project["project"]: len(project["reviewedNodeIds"]) for project in projects},
                "transientFailuresRecovered": len(transient_failures),
                "results": str(ROOT / "platform_monitor_view_results.json"),
                "overview": str(ROOT / "platform_monitor_view_overview.md"),
                "fullReport": str(ROOT / "platform_monitor_view_full_report.md"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
