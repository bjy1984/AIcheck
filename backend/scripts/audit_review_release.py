"""Reproducible 69-rule release inventory. Compilation is not business acceptance."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

from libs.business_pack import load_business_pack
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools.business_tools import DOMAIN_TOOL_NAMES, profile_business_handler
from libs.review_tools.executor import compile_node_tool_plan, execute_node_tool_plan

ROOT = Path(__file__).resolve().parents[1]


def dedicated_handlers() -> set[str]:
    tree = ast.parse((ROOT / 'libs/review_tools/business_tools.py').read_text())
    dispatch = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'dispatch_business_tool')
    mapping = next(node.value for node in dispatch.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == 'handlers')
    return {key.value for key in mapping.keys}


def audit(pack: dict[str, Any] | None = None) -> dict[str, Any]:
    pack = pack or load_business_pack('engineering_inspection_v1')
    available = {item['name'] for item in runtime_tool_catalog()}
    generic = set(DOMAIN_TOOL_NAMES) - dedicated_handlers()
    rows = []
    for number in range(1, 70):
        rule = f'R{number:02d}'
        plan = compile_node_tool_plan(pack, rule, available_tools=available)
        output = execute_node_tool_plan(plan, tool_runner=lambda name, args: dispatch_runtime_tool({}, name, args))
        generic_bindings = [(binding, name) for binding in plan for name in binding['tools']
                            if name in generic and profile_business_handler(name, binding['parameters'].get('profile')) is None]
        generic_tools = sorted({name for _, name in generic_bindings})
        unconfigured = sorted({name for binding, name in generic_bindings if not binding['parameters'].get('ruleChecks')})
        specialized = [{'atomicCheckId': binding['atomicCheckId'], 'tool': name, 'profile': binding['parameters']['profile']}
                       for binding in plan for name in binding['tools']
                       if profile_business_handler(name, binding['parameters'].get('profile')) is not None]
        pending = sorted({capability for binding in plan for capability in binding['parameters'].get('pendingCapabilities', [])})
        rows.append({'rule': rule, 'atomicChecks': len(plan), 'pilotEnabled': rule in pack['atomicCheckToolBindingSet']['pilotRules'],
                     'allToolsRegistered': bool(plan) and all(item['compilable'] for item in plan),
                     'requiredFacts': sorted({field for item in plan for field in item['requiredFacts']}),
                     'genericInterpreters': generic_tools, 'unconfiguredInterpreters': unconfigured,
                     'profileDedicatedTools': specialized, 'pendingCapabilities': pending,
                     'emptyInputResult': output['result'],
                     'evidenceGroundingBound': all('validate_evidence_grounding' in item['tools'] for item in plan),
                     'scenarioAcceptance': {name: 'not_recorded' for name in ('compliant', 'noncompliant', 'insufficient', 'not_applicable')},
                     'atomicBindings': plan})
    # No invented acceptance result: even dedicated handlers require real frozen
    # facts, four scenarios and document evidence before the release is approved.
    return {'schemaVersion': 'review-release-audit-v1', 'bindingSetVersion': pack['atomicCheckToolBindingSet']['version'],
            'lifecycleStatus': pack['atomicCheckToolBindingSet']['lifecycleStatus'], 'ruleCount': len(rows),
            'atomicCheckCount': sum(row['atomicChecks'] for row in rows), 'releaseReady': False,
            'blockers': ['four_scenario_business_acceptance_not_recorded'] +
                        (['unconfigured_generic_interpreters'] if any(row['unconfiguredInterpreters'] for row in rows) else []) +
                        (['pending_business_capabilities'] if any(row['pendingCapabilities'] for row in rows) else []),
            'rules': rows}


def markdown(report: dict[str, Any]) -> str:
    lines = ['# 69 条规则发布验收矩阵', '',
             '此表由 `backend/scripts/audit_review_release.py` 产生。空输入探针只验证防误通过；工具注册及编译不代表业务验收完成。', '',
             '四情境（符合／不符合／证据不足／不适用）及文件证据定位尚需逐条留存真实验收记录。全量发布门槛尚未达成。', '',
             '| 规则 | 原试点 | 原子项 | 注册完整 | 空输入结果 | 未配置规则档案的通用工具 | 尚未完成能力 |',
             '|---|---|---:|---|---|---|---|']
    for row in report['rules']:
        lines.append(f"| {row['rule']} | {'是' if row['pilotEnabled'] else '否'} | {row['atomicChecks']} | {row['allToolsRegistered']} | {row['emptyInputResult']} | {', '.join(row['unconfiguredInterpreters']) or '—'} | {', '.join(row['pendingCapabilities']) or '—'} |")
    lines += ['', '完整必要事实、绑定及证据工具栏位见同目录 JSON。`—` 只代表没有发现此类静态缺口，仍须业务情境验收。', '']
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-release', action='store_true')
    args = parser.parse_args()
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    args.output.with_suffix('.md').write_text(markdown(report))
    print(json.dumps({key: value for key, value in report.items() if key != 'rules'}, ensure_ascii=False))
    return 1 if args.check_release and not report['releaseReady'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
