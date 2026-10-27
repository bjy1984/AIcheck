"""Run harness2's real recursion + library workflow on the aicheck-node-audit skeleton adapter.

No model, no network, no real project data: the world is two synthetic text-only projects and synthetic
gold answers. Run from source, nothing installed:

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<harness2 checkout> python3.12 run_skeleton.py --out <dir>

harness2 needs Python 3.12 or 3.13 and has no third-party dependencies on this path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import skill_tree as ST
from aicheck_h2 import SKILL_SRC, AicheckAdapter, FakeProposer
from harness2.core.judge import judge_selections
from harness2.core.schedule import mode_token, run_domain

PROJECTS = {
    "a": {"plan": ("2026-03-25", "2026-06-30"), "valid": "2026-12-25", "no": "TS3800000-2026"},
    "b": {"plan": ("2026-04-01", "2026-07-15"), "valid": "2027-01-10", "no": "TS3800001-2026"},
}


def build_world(root: Path) -> None:
    """Synthetic node-02 projects (construction-unit licence) and their gold answers."""
    world = root / "world"
    tasks = []
    for key, p in PROJECTS.items():
        project = world / "projects" / key
        (project / "施工合同").mkdir(parents=True, exist_ok=True)
        (project / "资质").mkdir(exist_ok=True)
        (project / "施工合同" / "监检合同.txt").write_text(
            f"压力管道安装监督检验合同。计划施工时间：{p['plan'][0]} 至 {p['plan'][1]}。", encoding="utf-8")
        (project / "资质" / "安装许可证.txt").write_text(
            f"特种设备生产许可证 编号 {p['no']}。许可子项目：工业管道安装（GC2）。有效期至 {p['valid']}。", encoding="utf-8")
        gold = {
            "schemaVersion": "aicheck-node-audit-gold@1", "id": f"synthetic-02-{key}",
            "checks": {"AC-R02-01": {"verdict": "evidence_insufficient", "accept": ["human_review_required"]},
                       "AC-R02-02": {"verdict": "passed"},
                       "AC-R02-03": {"verdict": "passed", "accept": ["not_applicable"]},
                       "AC-R02-04": {"verdict": "evidence_insufficient"}},
            "keyFacts": [{"id": "K1", "desc": "计划施工期", "where": "AC-R02-02", "anyOf": [[p["plan"][0], p["plan"][1]]], "citeFile": "监检合同", "weight": 2},
                         {"id": "K2", "desc": "许可有效期", "where": "AC-R02-02", "anyOf": [[p["valid"]]], "weight": 2}],
            "expectConflicts": [], "toolsUsed": [],
            "forbiddenPatterns": [{"id": "id-number", "validator": "id_number", "desc": "报告出现完整身份证号"}],
        }
        (world / "gold").mkdir(exist_ok=True)
        (world / "gold" / f"{key}.json").write_text(json.dumps(gold, ensure_ascii=False), encoding="utf-8")
        tasks.append({"id": f"syn-02-{key}", "node": 2, "domain": "license", "project": f"projects/{key}", "gold": f"gold/{key}.json"})
    (world / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--mode", choices=("parallel", "sequential", "both"), default="both")
    parser.add_argument("--reject-first", action="store_true", help="make the first proposal carry an off-surface references/ file")
    args = parser.parse_args()
    root = args.out.expanduser().resolve()
    build_world(root)
    adapter = AicheckAdapter(root)
    proposer = FakeProposer(adapter.spec.channels["proposer"])
    proposer.reject_first = args.reject_first
    modes = ("agg", "seq") if args.mode == "both" else (mode_token(args.mode),)
    result = run_domain("license", adapter.tasks(), args.k, adapter=adapter, prop=proposer,
                        runs_root=adapter.spec.runs_root, library_root=root / "library" / f"k{args.k}", modes=modes)
    (root / "run.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"workflow: {result['done']} tasks done, {result['failed']} failed; "
          f"{adapter.execution_count} executions, {len(proposer._calls)} scripted editor/selector calls")

    # After the loop: the judge. Nothing above this line saw a gold answer.
    selections = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "runs").rglob("selection.json"))]
    judged = judge_selections(adapter, selections)
    print("\nchosen run per task and mode, judged by eval/score.py against the synthetic gold:")
    for row in sorted(judged, key=lambda r: (r.task_id, r.mode)):
        pct = row.raw.get("percent")
        print(f"  {row.task_id} {row.mode:>3}  chosen={'BASE' if row.chosen_is_base else 'adapted':7}  "
              f"{row.n_passed}/{row.n_criteria} points ({pct}%)  critical={row.raw.get('critical')}  {row.error}")
    print("\nbase harness on the same tasks, for comparison:")
    for task_id in adapter.tasks():
        got = adapter.score(adapter.execute(task_id, None, f"base-check-{task_id}"), task_id)
        print(f"  {task_id}  base    {got['n_passed']}/{got['n_criteria']} points ({got['percent']}%)  critical={got['critical']}")
    print(f"\nlibrary written under {root / 'library'}")

    # And back: the adopted harness becomes a NEW skill directory, with a report of what changed (the live skill is untouched).
    adopted = sorted((root / "library").rglob("harnesses/*/harness"))
    if adopted:
        report = ST.import_tree(ST.read_tree_dir(adopted[0]), root / "back-to-skill", base_skill_dir=SKILL_SRC)
        print(f"adopted harness written back as a skill directory: {report['outDir']}")
        print(f"  files that differ from the live skill: {report['changed']}; harness-only files changed: {report['harnessOnlyChanged']}")
    return int(result["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
