"""把 out/<date>/ 下的基准结果汇总成 Markdown 表（P8 §11.1 与 P12 §17.3 的指标）。

用法：python3 scripts/experiments/summarize.py --date 2026-09-06
输出：out/<date>/summary.md 与 summary.json；直接贴进优化计划的度量表。
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path


def load(pattern: str, out_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(out_dir.glob(pattern)):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(payload.get("record", payload))
    return rows


def review_table(rows: list[dict]) -> str:
    header = (
        "| 模型 | 节点 | 状态 | 耗时 s | 调用 | 失败分片 | 信封错误 | 输入 token | 输出 token | 发现 | 通过守卫 | 模板标题 | 重复标题 | 正文中位/最长 | 正文>150 | 摘要为模板 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    body = ""
    for row in rows:
        body += (
            f"| {row.get('model')} | {row.get('project')} #{row.get('node')} | {row.get('status') or row.get('exception') or row.get('errorCode') or '-'} "
            f"| {row.get('elapsedSeconds', '-')} | {row.get('llmCalls', '-')} | {row.get('failedShards', '-')}/{row.get('shardCount', '-')} "
            f"| {row.get('envelopeErrors', '-')} | {row.get('inputTokens', '-')} | {row.get('outputTokens', '-')} | {row.get('findings', '-')} "
            f"| {row.get('grounded', '-')} | {row.get('templateTitles', '-')} | {row.get('duplicateTitles', '-')} "
            f"| {row.get('descriptionMedianChars', '-')}/{row.get('descriptionMaxChars', '-')} | {row.get('descriptionOver150', '-')} "
            f"| {'是' if row.get('opinionDraftIsTemplate') else '否'} |\n"
        )
    return header + body


def pa_table(rows: list[dict]) -> str:
    header = "| 模型 | 节点批 | 校验 | 耗时 s | 输入/输出 token | 发现 | 引用通过 | 各节点结论 |\n|---|---|---|---|---|---|---|---|\n"
    body = ""
    for row in rows:
        usage = row.get("usage") or {}
        per_node = "；".join(
            f"{item.get('nodeId')}:{item.get('result')}({item.get('findings')})"
            for item in row.get("perNode") or []
        )
        body += (
            f"| {row.get('model')} | {row.get('nodes')} | {'通过' if row.get('valid') else (row.get('error') or row.get('exception') or '失败')} "
            f"| {row.get('elapsedSeconds', '-')} | {usage.get('inputTokens', '-')}/{usage.get('outputTokens', '-')} | {row.get('findings', '-')} "
            f"| {row.get('withEvidence', '-')} | {per_node} |\n"
        )
    return header + body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--out-root", default=str(Path(__file__).resolve().parent / "out"))
    args = parser.parse_args()
    out_dir = Path(args.out_root) / args.date
    reviews = load("review-*.json", out_dir)
    analyses = load("pa-*.json", out_dir)
    summary = {
        "date": args.date,
        "reviewRuns": reviews,
        "projectAnalyses": analyses,
        "aggregate": {
            "reviewRuns": len(reviews),
            "groundedTotal": sum(int(row.get("grounded") or 0) for row in reviews),
            "findingsTotal": sum(int(row.get("findings") or 0) for row in reviews),
            "templateTitleTotal": sum(int(row.get("templateTitles") or 0) for row in reviews),
            "envelopeErrorTotal": sum(int(row.get("envelopeErrors") or 0) for row in reviews),
            "failedShardTotal": sum(int(row.get("failedShards") or 0) for row in reviews),
        },
    }
    markdown = f"# 基准汇总 {args.date}\n\n## 节点级审查\n\n{review_table(reviews)}\n## 一键分析\n\n{pa_table(analyses)}"
    (out_dir / "summary.md").write_text(markdown, encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
