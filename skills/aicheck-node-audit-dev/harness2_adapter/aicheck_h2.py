"""aicheck-node-audit as a harness2 benchmark: skeleton adapter, no model anywhere.

What is real here: the harness tree layout and harness2's own validation of it, the skill's real
node_audit.py (local-init, skeleton, report), and the real eval/score.py as the after-the-fact judge.
What is a stand-in: the solver (`execute`) fills the skeleton with deterministic rules instead of a
model, and `FakeProposer` plays the improver and selector with deterministic rules.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import skill_tree as ST
from harness2.core import tree
from harness2.core.proposer import Proposer, Reply
from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec
from harness2.substrate.opencode import OpencodeSubstrate

REPO = Path(os.environ.get("AICHECK_REPO") or HERE.parents[2])
SKILL_SRC = REPO / "skills" / "aicheck-node-audit"
SCORE_PY = HERE.parent / "eval" / "score.py"
SKILL_MD, SCRIPT = ST.SKILL_MD, ST.SCRIPT
NAME = ST.NAME


def _tool_python() -> str:
    """The interpreter that runs node_audit.py: it needs PyYAML for the local business pack."""
    if os.environ.get("AICHECK_TOOL_PYTHON"):
        return os.environ["AICHECK_TOOL_PYTHON"]
    venv = REPO / "backend" / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


TOOL_PYTHON = _tool_python()
# The rule the deterministic improver adds, and the marker the deterministic solver looks for.
RULE_MARK = "条件没有触发"
RULE_LINE = "- 检查写成“如果…才…”且条件没有触发：判 passed 符合，理由写条件事实，不判 not_applicable 不适用。\n"


def _load_score():
    spec = importlib.util.spec_from_file_location("aicheck_score_py", SCORE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base_tree(*, simulate_before_rule: bool = True) -> dict[str, str]:
    """The skill as a harness2 tree. With `simulate_before_rule` the conditional-clause row is dropped, standing in
    for the skill as it was before that rule existed, so the deterministic improver has something to fix."""
    base = ST.export_tree(SKILL_SRC)
    if simulate_before_rule:
        base[SKILL_MD] = "".join(line for line in base[SKILL_MD].splitlines(keepends=True) if RULE_MARK not in line)
    return base


class AicheckAdapter:
    """Tasks come from `<root>/world/tasks.json`: [{id, node, domain, project, gold}]."""

    def __init__(self, root: Path, *, simulate_before_rule: bool = True):
        self.root = Path(root)
        self.substrate = OpencodeSubstrate()
        channel = ChannelSpec("opencode", "local/deterministic")
        self.spec = BenchSpec(
            name="aicheck-node-audit",
            runs_root=self.root / "runs",
            install_mode="workspace_config",
            prompts=BenchPrompts(
                work="audit one engineering node of a pressure-pipeline inspection project against that node's "
                     "rules, and report every atomic check with a conclusion and page-level evidence"
            ),
            channels={"proposer": channel, "selector": channel},
            leak_globs=("gold*", "*.gold.json"),
        )
        self.execution_count = 0
        self._tasks = {t["id"]: t for t in json.loads((self.root / "world" / "tasks.json").read_text(encoding="utf-8"))}
        self._score = _load_score()
        tree.write_tree(self.substrate.surface(), base_tree(simulate_before_rule=simulate_before_rule), self.base_harness(), stubs=False)

    # -- the adapter protocol ------------------------------------------------------------------
    def tasks(self, split: str = "all") -> list[str]:
        return sorted(self._tasks)

    def domain_of(self, task_id: str) -> str:
        return self._tasks[task_id]["domain"]

    def task_prompt(self, task_id: str) -> str:
        t = self._tasks[task_id]
        return (f"Audit node {t['node']:02d} of the project in the source folder, following the `{NAME}` skill. "
                f"Deliver audit.md: every atomic check with a conclusion, its reasoning and where each fact was read.")

    def task_files(self, task_id: str) -> Path:
        return self.root / "world" / self._tasks[task_id]["project"]

    def base_harness(self) -> Path:
        return self.root / "base"

    def validate_tree(self, harness: tree.Tree) -> None:
        problems = ST.check_tree(harness, expected_references=ST.reference_names(SKILL_SRC))
        if problems:
            raise ValueError(" | ".join(problems))

    def execute(self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None) -> Path:
        self.execution_count += 1
        run_dir = self.root / "executions" / run_id
        if (run_dir / ".complete").is_file():
            return run_dir
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir(parents=True)
        harness = Path(harness_dir) if harness_dir else self.base_harness()
        task = self._tasks[task_id]
        script = harness / SCRIPT
        env = {**os.environ, "AICHECK_AUDIT_HOME": str(run_dir / "home"), "AICHECK_REPO": str(REPO), "PYTHONDONTWRITEBYTECODE": "1"}
        bundle = run_dir / "bundle"
        log: list[str] = []

        def tool(*args: str) -> dict:
            done = subprocess.run([str(TOOL_PYTHON), str(script), *args], capture_output=True, text=True, env=env,
                                  timeout=timeout or 180, check=False)
            log.append(f"[ACTION] node_audit.py {args[0]} {' '.join(a for a in args[1:] if not a.startswith('/'))}\n"
                       f"[OBSERVATION]\n{done.stdout[:1200]}")
            data = json.loads(done.stdout)
            if not data.get("ok"):
                raise RuntimeError(f"node_audit.py {args[0]} failed: {data.get('error')}")
            return data["data"]

        tool("local-init", "--node", str(task["node"]), "--project-dir", str(self.task_files(task_id)), "--out", str(bundle))
        tool("skeleton", "--bundle", str(bundle))
        self._fill_deterministically(bundle, self._policy(harness))
        tool("report", "--bundle", str(bundle))
        (run_dir / "trajectory.md").write_text("\n\n".join(log), encoding="utf-8")
        (run_dir / ".complete").write_text("ok", encoding="utf-8")
        return run_dir

    def delivered(self, run_dir: Path) -> bool:
        return (run_dir / "bundle" / "audit.md").is_file()

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        return (run_dir / "trajectory.md").read_text(encoding="utf-8")

    def deliverable_text(self, run_dir: Path) -> str:
        return (run_dir / "bundle" / "audit.md").read_text(encoding="utf-8")

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        return {"audit.md": self.deliverable_text(run_dir)}

    def score(self, run_dir: Path, task_id: str) -> dict | None:
        """The after-the-fact judge: the skill's own scorer against a gold answer. The improvement loop never calls this."""
        gold = json.loads((self.root / "world" / self._tasks[task_id]["gold"]).read_text(encoding="utf-8"))
        got = self._score.score(gold, run_dir / "bundle")
        return {"n_passed": round(got["points"] * 2), "n_criteria": round(got["max"] * 2),
                "all_pass": got["all_pass"], "percent": got["percent"], "critical": got["critical"],
                "standardEvidence": got["standardEvidence"], "scoreSchemaVersion": got["schemaVersion"]}

    # -- the deterministic stand-in for the model that would run the skill -----------------------
    @staticmethod
    def _policy(harness: Path) -> dict:
        text = (harness / SKILL_MD).read_text(encoding="utf-8")
        return {"conditional_passes": RULE_MARK in text}

    def _fill_deterministically(self, bundle: Path, policy: dict) -> None:
        path = bundle / "audit.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        files = {Path(f["file"]).name: f["file"] for f in report["reviewedFiles"]}
        text = {name: (bundle / "text" / name).read_text(encoding="utf-8") if (bundle / "text" / name).is_file()
                else (bundle / rel).read_text(encoding="utf-8") for name, rel in files.items()}
        body = "\n".join(text.values())
        plan = re.search(r"计划施工时间[：:]\s*(\d{4}-\d\d-\d\d)\s*至\s*(\d{4}-\d\d-\d\d)", body)
        valid = re.search(r"有效期至\s*(\d{4}-\d\d-\d\d)", body)
        if not (plan and valid):
            raise RuntimeError("synthetic project lacks the plan period or the licence validity")
        if valid.group(1) < plan.group(2):
            raise RuntimeError("the skeleton only models the covered case")
        contract = next(rel for name, rel in files.items() if "合同" in name)
        licence = next(rel for name, rel in files.items() if "许可证" in name)

        def fact(name: str, value: str, rel: str) -> dict:
            return {"name": name, "value": value, "source": {"file": rel, "locator": f"text/{Path(rel).name} 第 1 行", "excerpt": value}}

        checks = {c["atomicCheckId"]: c for c in report["checks"]}
        checks["AC-R02-01"].update(verdict="evidence_insufficient", reason="资料包没有设计文件，无法核对管道级别")
        checks["AC-R02-02"].update(
            verdict="passed", requirement="许可有效期覆盖计划施工期",
            facts=[fact("计划施工期", f"{plan.group(1)} 至 {plan.group(2)}", contract), fact("许可有效期至", valid.group(1), licence)],
            reasoning=f"有效期至 {valid.group(1)}，晚于计划施工期结束日 {plan.group(2)}，整段覆盖。")
        if policy["conditional_passes"]:
            checks["AC-R02-03"].update(
                verdict="passed", requirement="不能覆盖时发联络单",
                facts=[fact("有效期是否覆盖", "覆盖，条件不成立", licence)], reasoning="条件“不能覆盖”没有触发，无需联络单。")
        else:
            checks["AC-R02-03"].update(verdict="not_applicable", reason="条件“不能覆盖”不成立，本项不适用")
        checks["AC-R02-04"].update(verdict="evidence_insufficient", reason="AC-R02-01 证据不足，证据追溯项不能判符合")
        report.update(summary="deterministic stand-in for a model run", auditor="deterministic-solver (no model)",
                      auditedAt="2026-10-23T00:00:00+08:00")
        for entry in report["reviewedFiles"]:
            entry.update(method="read", pages="all")
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


class FakeProposer(Proposer):
    """Scripted improver and selector. A real run replaces this class with `Proposer`, which drives a model."""

    reject_first = False  # first proposal carries an off-surface file, to see harness2 reject it and retry

    def call(self, mission, context_dir, label, **kwargs) -> Reply:
        context = Path(context_dir)
        workspace = None
        if label.startswith("select."):
            # What a model selector would do from the candidates alone: prefer the report that follows the skill's
            # own rule (a "if … then …" check whose condition did not happen is passed, not not_applicable).
            def verdict(path: Path) -> str:
                m = re.search(r"## AC-R02-03[^\n]*\n\n\*\*结论：([^*]+)\*\*", path.read_text(encoding="utf-8"))
                return m.group(1) if m else ""
            candidates = sorted((context / "candidates").glob("*.md"))
            chosen = next((p.stem for p in candidates if verdict(p) == "符合"), candidates[0].stem)
            text = f"<why>Its AC-R02-03 follows the skill's rule for conditional checks.</why>\n```choice\n{chosen}\n```"
        elif label.startswith("experience."):
            skill = SKILL_MD
            changed = (context / "harness" / skill).read_text(encoding="utf-8") != (context / "base_harness" / skill).read_text(encoding="utf-8")
            text = (
                "<edits>\ncomponent: " + skill + "\ncandidates: inv1\n"
                "change: added a rule for conditional checks whose condition did not happen\n"
                "observed: the adapted run concluded passed where the base run concluded not_applicable\n"
                f"verdict: {'helped' if changed else 'no observed effect'}\n</edits>\n\n"
            ) + (
                "<experience>\ncue: A check is phrased as \"if X then Y\" and X did not happen\n"
                "lesson: Conclude passed and state the condition facts; not_applicable is only for what the original text says.\n"
                "evidence: AC-R02-03 in the adapted run is passed with the covering validity as its fact.\n"
                "confidence: high for this observed contrast\n</experience>"
                if changed else "NO_ENTRY"
            )
        else:
            workspace = context / "harness"
            skill = workspace / SKILL_MD
            folded = skill.read_text(encoding="utf-8")
            if RULE_LINE not in folded:
                # Add it to the skill's own text, not to the end of the file: the end of the folded file is the last reference.
                body, refs = ST.unfold(folded)
                skill.write_text(ST.refold(body.rstrip("\n") + "\n\n" + RULE_LINE, refs), encoding="utf-8")
            stray = workspace / "references" / "extra.md"
            if self.reject_first and label.endswith(".a1") and not getattr(self, "_rejected_once", False):
                self._rejected_once = True
                stray.parent.mkdir(parents=True, exist_ok=True)
                stray.write_text("an extra reference file", encoding="utf-8")
            elif stray.parent.is_dir():
                shutil.rmtree(stray.parent)
            text = "<notes>Added the conditional-check rule: not triggered means passed, with the condition facts.</notes>"
        reply = Reply(label=label, text=text, ok=True, attempts=1, workspace=workspace)
        self._calls.append(reply)
        return reply
