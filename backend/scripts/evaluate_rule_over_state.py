"""对生产库里的真实文件离线跑一条规则，只读，不产生审查运行。

用途：密钥恢复后，`run_domain_judgment.py --persist` 把 agent 读正文得到的判断写进
domain_judgments，然后用这个脚本让 R43 的事实构建 + 冻结判据在真实资料上出结论，
一路不调模型——事实构建本来就是离线的，agent 的产出已经是记在 state 里的证据。

不建立 review_run、不写 rule_check_results，纯粹回答"这条规则对这份文件现在会判成什么"。

    python3 scripts/evaluate_rule_over_state.py --rule R43 \
        --project-id P-2026-ECD202 --tenant-id TENANT-DEFAULT \
        --document-version-id DV-D66DB781-V1
"""

from __future__ import annotations

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rule", required=True, help="如 R43")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--document-version-id", required=True, action="append",
                        help="可重复给多份")
    parser.add_argument("--object-id", action="append", default=[],
                        help="审哪个对象；多行表不给就是来源含糊")
    parser.add_argument("--pack-id", default="engineering_inspection_v1")
    args = parser.parse_args()

    from libs.business_pack import load_business_pack
    from libs.db import repository
    from libs.review_document_scope import freeze_document_scope
    from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
    from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
    from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan

    node = int(args.rule[1:])
    builder = NDT_FACT_BUILDERS.get(node)
    if builder is None:
        raise SystemExit(f"{args.rule} 没有注册重放用的事实构建器")

    # 只读加载事实构建会碰到的集合；不调 load_state() 全量，那会顺手补种数据。
    repository.load_state({"documents", "versions", "ocr_parse_results", "domain_judgments"})
    state = repository.repo.state
    run = {
        "projectId": args.project_id, "tenantId": args.tenant_id, "nodeId": node,
        "inputDocumentVersionIds": list(args.document_version_id),
    }
    if args.object_id:
        run["selectedObjectIds"] = list(args.object_id)
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)

    facts = builder(state, run)
    pack = load_business_pack(args.pack_id)
    plan = compile_node_tool_plan(pack, args.rule,
                                  available_tools={item["name"] for item in runtime_tool_catalog()})
    judgment = facts.get("judgment") or {}
    output = execute_node_tool_plan(
        plan, facts=facts, document_version_ids=run["inputDocumentVersionIds"],
        evidence_facts=judgment.get("claimedFacts") or [],
        evidence_refs=judgment.get("evidenceRefs") or [],
        tool_runner=lambda name, a: dispatch_runtime_tool(state, name, a, context={"reviewRun": run}),
    )
    domains, issues = [], {}
    for namespace, block in facts.items():
        if isinstance(block, dict):
            for key, val in block.items():
                if isinstance(val, dict) and "domains" in val:
                    domains.extend(val["domains"])
                    for k in ("sourceIssues", "selectionIssues"):
                        if val.get(k):
                            issues[f"{namespace}.{key}.{k}"] = val[k]
    summary = {
        "rule": args.rule,
        "result": output.get("result"),
        "selectedObjectIds": run.get("selectedObjectIds"),
        "domainRowsBuilt": len(domains),
        "issues": issues,
        "judgmentRowsInState": sum(1 for r in state.get("domain_judgments") or []
                                   if r.get("nodeId") == node and r.get("projectId") == args.project_id),
        "atomicResults": [
            {"atomicCheckId": row.get("atomicCheckId"), "result": row.get("result"),
             "checks": [(c.get("code"), c.get("result"), c.get("actual"))
                        for tr in (row.get("toolResults") or []) if isinstance(tr, dict)
                        for c in ((tr.get("facts") or {}).get("processChecks") or [])][:20]}
            for row in output.get("atomicResults") or []
        ],
        "firstDomainRow": domains[0] if domains else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
