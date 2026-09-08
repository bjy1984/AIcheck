"""Reproducible 69-rule release inventory. Compilation is not business acceptance."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

from libs.business_pack import load_business_pack
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools.business_tools import DOMAIN_TOOL_NAMES
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
        generic_tools = sorted({name for binding in plan for name in binding['tools'] if name in generic})
        unconfigured = sorted({name for binding in plan for name in binding['tools'] if name in generic and not binding['parameters'].get('ruleChecks')})
        rows.append({'rule': rule, 'atomicChecks': len(plan), 'pilotEnabled': rule in pack['atomicCheckToolBindingSet']['pilotRules'],
                     'allToolsRegistered': bool(plan) and all(item['compilable'] for item in plan),
                     'requiredFacts': sorted({field for item in plan for field in item['requiredFacts']}),
                     'genericInterpreters': generic_tools, 'unconfiguredInterpreters': unconfigured,
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
                        (['unconfigured_generic_interpreters'] if any(row['unconfiguredInterpreters'] for row in rows) else []),
            'rules': rows}


def markdown(report: dict[str, Any]) -> str:
    lines = ['# 69 條規則發布驗收矩陣', '',
             '此表由 `backend/scripts/audit_review_release.py` 產生。空輸入探針只驗證防誤通過；工具註冊及編譯不代表業務驗收完成。', '',
             '四情境（符合／不符合／證據不足／不適用）及文件證據定位尚需逐條留存真實驗收記錄。全量發布門檻尚未達成。', '',
             '| 規則 | 原試點 | 原子項 | 註冊完整 | 空輸入結果 | 未配置規則檔案的通用工具 |',
             '|---|---|---:|---|---|---|']
    for row in report['rules']:
        lines.append(f"| {row['rule']} | {'是' if row['pilotEnabled'] else '否'} | {row['atomicChecks']} | {row['allToolsRegistered']} | {row['emptyInputResult']} | {', '.join(row['unconfiguredInterpreters']) or '—'} |")
    lines += ['', '完整必要事實、綁定及證據工具欄位見同目錄 JSON。`—` 只代表沒有發現此類靜態缺口，仍須業務情境驗收。', '']
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
