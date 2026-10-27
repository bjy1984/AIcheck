"""One real harness2 round on one node: Codex runs the skill, Codex improves it, the gold judges afterwards.

    loop   (gold hidden by `eval/isolate.py prepare`): write the task, run harness2's run_domain
    judge  (after `eval/isolate.py finish`): score every rollout with eval/score.py, write the adopted harness back
           out as a skill directory next to the run (never over the live skill)

    PYTHONDONTWRITEBYTECODE=1 <harness2 venv>/bin/python run_codex.py loop --root R --project P --node 2 --label L
    PYTHONDONTWRITEBYTECODE=1 <harness2 venv>/bin/python run_codex.py judge --root R --gold G
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import skill_tree as ST  # noqa: E402
from codex_h2 import SKILL_SRC, CodexAdapter, CodexProposer  # noqa: E402
from harness2.core.schedule import mode_token, run_domain  # noqa: E402

AUDIT_HOME = Path.home() / ".aicheck-node-audit"


def loop(args: argparse.Namespace) -> int:
    if AUDIT_HOME.exists() or not AUDIT_HOME.with_name(AUDIT_HOME.name + ".hold").is_dir():
        raise SystemExit("run `eval/isolate.py prepare` first: the gold answers must be hidden during the loop")
    root = args.root.expanduser().resolve()
    (root / "world").mkdir(parents=True, exist_ok=True)
    task = {"id": f"node-{args.node:02d}", "node": args.node, "domain": f"node-{args.node:02d}",
            "project": str(args.project.expanduser().resolve()), "label": args.label}
    (root / "world" / "tasks.json").write_text(json.dumps([task], ensure_ascii=False), encoding="utf-8")
    adapter = CodexAdapter(root, timeout=args.timeout)
    proposer = CodexProposer(adapter.spec.channels["proposer"], audit_dir=root / "proposer")
    started = time.time()
    result = run_domain(task["domain"], adapter.tasks(), args.k, adapter=adapter, prop=proposer,
                        runs_root=adapter.spec.runs_root, library_root=root / "library" / f"k{args.k}",
                        modes=(mode_token(args.mode),))
    result["wall_s"] = round(time.time() - started, 1)
    (root / "run.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"done": result["done"], "failed": result["failed"], "wall_s": result["wall_s"],
                      "proposerCalls": [(r.label, r.ok, r.wall_s, r.error[:200]) for r in proposer._calls]},
                     ensure_ascii=False, indent=2))
    return int(result["failed"] > 0)


def judge(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    adapter = CodexAdapter(root)
    (task_id,) = adapter.tasks()
    adapter.set_gold({task_id: args.gold})
    rows = []
    for run_dir in sorted(p.parent for p in (root / "executions").rglob("stream.jsonl")):  # run ids nest: <ns>/<task>/<label>
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8")) if (run_dir / "meta.json").is_file() else {}
        row = {"run": str(run_dir.relative_to(root / "executions")), "delivered": adapter.delivered(run_dir), "wall_s": meta.get("wall_s"),
               "tokensIn": meta.get("input_tokens"), "tokensOut": meta.get("output_tokens")}
        if row["delivered"]:
            row.update(adapter.score(run_dir, task_id))
        rows.append(row)
    selections = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "runs").rglob("selection.json"))]
    out: dict = {"rollouts": rows, "selections": [{k: s.get(k) for k in ("mode", "chosen_label", "chosen_run_id", "why")}
                                                   for s in selections]}
    # The library keeps a harness only when the reflection wrote an experience entry; else take the selected tree.
    adopted = sorted((root / "library").rglob("harnesses/*/harness")) or [
        d for s in selections if s.get("chosen_label") for d in sorted((root / "runs").rglob(f"harnesses/{s['chosen_label']}"))]
    if adopted:
        back = root / "back-to-skill"
        out["writeBack"] = ST.import_tree(ST.read_tree_dir(adopted[-1]), back, base_skill_dir=SKILL_SRC, layout="codex") \
            if not back.exists() else {"outDir": str(back), "note": "already written"}
    (root / "judged.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


def status(args: argparse.Namespace) -> int:
    """Progress of a running or finished round, read from the files it leaves (harness2 itself logs nothing)."""
    root = args.root.expanduser().resolve()
    now = time.time()
    print("audits (Codex running the skill):")
    for stream in sorted((root / "executions").rglob("stream.jsonl"), key=lambda p: p.stat().st_mtime):
        run_dir = stream.parent
        commands = sum('"command_execution"' in line and '"item.completed"' in line
                       for line in stream.read_text(encoding="utf-8", errors="replace").splitlines())
        if (run_dir / "meta.json").is_file():
            meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
            state = f"done in {meta['wall_s'] / 60:.1f} min, report {'yes' if (run_dir / 'bundle' / 'audit.md').is_file() else 'NO'}"
        else:
            state = f"running, last output {now - stream.stat().st_mtime:.0f}s ago"
        print(f"  {run_dir.name:6} {commands:3} commands  {state}")
    print("improver / reflection sessions:")
    for meta_path in sorted((root / "proposer").glob("*.meta.json"), key=lambda p: p.stat().st_mtime):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        print(f"  {meta['label']:14} {'ok' if meta['ok'] else 'FAILED ' + meta['error'][:80]}  {meta['wall_s']:.0f}s")
    print("round finished" if (root / "run.json").is_file() else "round still running")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("loop")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--project", type=Path, required=True)
    p.add_argument("--node", type=int, required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--k", type=int, default=1)
    p.add_argument("--mode", choices=("parallel", "sequential"), default="parallel")
    p.add_argument("--timeout", type=int, default=3600, help="seconds per Codex session")
    p.set_defaults(func=loop)
    p = sub.add_parser("judge")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--gold", type=Path, required=True)
    p.set_defaults(func=judge)
    p = sub.add_parser("status")
    p.add_argument("--root", type=Path, required=True)
    p.set_defaults(func=status)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
