"""aicheck-node-audit as a harness2 benchmark with Codex everywhere: the solver runs the skill, the improver edits it.

The solver: each rollout gets its own workspace with the harness tree's AGENTS.md and the skill unfolded back into
SKILL.md + references/ + scripts/ (the same shape the live skill has), then `codex exec` audits one node of a local
project with the trial prompt in eval/codex-prompt.txt. The improver and the selector: `CodexProposer`, harness2's own
Proposer with its session runner swapped for `codex exec` (same MISSION.md / output/answer.md contract as OpenCode).

harness2 never sees a gold answer: the adapter takes the gold map only when the judge asks for `score`, after the loop.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import skill_tree as ST
from aicheck_h2 import REPO, RULE_MARK, SKILL_SRC, TOOL_PYTHON, _load_score
from harness2.core import tree
from harness2.core.proposer import Proposer
from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec
from harness2.substrate.codex import CodexSubstrate, _clip, final_message

LAYOUT = ST.LAYOUTS["codex"]
SKILL_MD, SCRIPT = LAYOUT["skill_md"], LAYOUT["script"]
PROMPT_TEMPLATE = HERE.parent / "eval" / "codex-prompt.txt"
CODEX = os.environ.get("AICHECK_H2_CODEX") or shutil.which("codex") or "codex"
CODEX_MODEL = os.environ.get("AICHECK_H2_CODEX_MODEL", "")  # empty: the account's default model
BASE_URL = os.environ.get("AICHECK_BASE_URL", "")
FOLD_NOTE = (
    f"The skill lives in the harness as ONE file, {SKILL_MD}: the skill's own text first, then each of its reference "
    "files behind a marker line `<!-- folded from references/<name>.md -->`. Before every run the file is split at those "
    f"markers back into skills/{ST.NAME}/SKILL.md and skills/{ST.NAME}/references/<name>.md, which is what the auditor "
    "reads. Edit the skill's text above the first marker and each reference below its own marker; keep every marker "
    f"line, and do not create references/ files (they are off the editable surface). {SCRIPT} must keep its masking of "
    "ID numbers (mask_value, is_id_number) and its report validator (check_report)."
)


def codex_exec(cwd: Path, prompt: str, *, stream: Path, last: Path, timeout: int, add_dirs: tuple[Path, ...] = (),
               network: bool = False, env: dict | None = None, ephemeral: bool = True) -> subprocess.CompletedProcess:
    """One non-interactive Codex session in `cwd`; the --json event stream goes to `stream`, the last message to `last`.

    With `ephemeral=False` Codex also keeps its session rollout under $CODEX_HOME/sessions (see `find_rollout`).
    """
    argv = [CODEX, "exec", "--ignore-user-config", "--skip-git-repo-check", *(["--ephemeral"] if ephemeral else []),
            "-C", str(cwd), "-s", "workspace-write", "--json", "-o", str(last)]
    if CODEX_MODEL:
        argv += ["-m", CODEX_MODEL]
    if network:
        argv += ["-c", "sandbox_workspace_write.network_access=true"]
    if (Path(cwd) / ".codex" / "hooks.json").is_file():
        argv.append("--dangerously-bypass-hook-trust")  # the harness's own hooks, written by the improver
    for d in add_dirs:
        argv += ["--add-dir", str(d)]
    with open(stream, "w", encoding="utf-8") as out:
        return subprocess.run(argv + ["-"], input=prompt, cwd=cwd, env=env or os.environ.copy(), text=True,
                              stdout=out, stderr=subprocess.PIPE, timeout=timeout, check=False)


def usage_of(stream: Path) -> dict:
    """Token totals from the turn.completed events of a --json stream."""
    total = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    for line in stream.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"turn.completed"' in line:
            usage = json.loads(line).get("usage") or {}
            for key in total:
                total[key] += int(usage.get(key) or 0)
    return total


def find_rollout(stream: Path, *, wait_s: float = 15.0) -> Path | None:
    """The session rollout of the run whose --json stream is `stream`. Codex writes it just after exiting, so wait a bit."""
    thread_id = ""
    for line in stream.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"thread.started"' in line:
            thread_id = json.loads(line).get("thread_id") or ""
            break
    if not thread_id:
        return None
    sessions = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    deadline = time.time() + wait_s
    while True:
        found = sorted(sessions.rglob(f"rollout-*{thread_id}.jsonl")) if sessions.is_dir() else []
        if found or time.time() >= deadline:
            return found[-1] if found else None
        time.sleep(0.5)


_TOOL_CALL = re.compile(r"tools\.([A-Za-z_]+)\(\s*(?=\{)")


def render_rollout(path: Path, *, obs_trunc: int, max_chars: int, args_trunc: int = 2000) -> str:
    """A Codex session rollout in harness2's trajectory grammar, including what the --json stream leaves out.

    `codex exec --json` never reports image views, and harness2's renderer skips `custom_tool_call` records, which is
    where this Codex version puts every tool call (`tools.exec_command`, `tools.view_image`, ...). Without this the
    improver reads an auditor that never looked at a page image. Images themselves are replaced by a placeholder.
    """
    lines: list[str] = []
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        payload = event.get("payload") if event.get("type") == "response_item" else None
        if not isinstance(payload, dict):
            continue
        kind = payload.get("type")
        if kind == "message":
            text = "\n".join(c.get("text", "") for c in payload.get("content") or [] if isinstance(c, dict)).strip()
            role = payload.get("role")
            if not text or role == "developer":
                continue
            if role == "assistant":
                lines.append(f"[ASSISTANT] {_clip(text, obs_trunc)}")
            elif text.startswith("# AGENTS.md instructions"):
                lines.append(f"[HARNESS AGENTS.md] {_clip(text, obs_trunc)}")
            elif not text.startswith("<"):  # Codex's own injected blocks (<environment_context>, plugins, ...) are not the task
                lines.append(f"[USER] {_clip(text, obs_trunc)}")
        elif kind in ("custom_tool_call", "function_call"):
            source = payload.get("input") if kind == "custom_tool_call" else payload.get("arguments")
            lines.append(_render_call(payload.get("name") or "tool", str(source or ""), args_trunc))
        elif kind in ("custom_tool_call_output", "function_call_output"):
            output = payload.get("output")
            parts = output if isinstance(output, list) else [{"type": "input_text", "text": str(output or "")}]
            text = "\n".join(str(p.get("text", "")) for p in parts
                             if isinstance(p, dict) and p.get("type") != "input_image")
            # Long text must not erase the fact that images followed it. Markers
            # count returned images, not attempted view calls or text descriptions.
            images = ["(image shown to the model)" for p in parts
                      if isinstance(p, dict) and p.get("type") == "input_image"]
            full = "\n".join("(image shown to the model)" if p.get("type") == "input_image" else str(p.get("text", ""))
                             for p in parts if isinstance(p, dict))
            # Keep the original text/image ordering when nothing needs clipping.
            observation = full if obs_trunc <= 0 or len(full) <= obs_trunc else "\n".join([_clip(text, obs_trunc), *images]).strip()
            lines.append(f"[OBSERVATION] {observation}")
        elif kind == "reasoning":
            text = "\n".join(s.get("text", "") for s in payload.get("summary") or [] if isinstance(s, dict)).strip()
            if text:
                lines.append(f"[REASONING] {_clip(text, obs_trunc)}")
    rendered = "\n".join(lines).strip() or "(no parseable events in rollout)"
    return rendered if len(rendered) <= max_chars else rendered[:max_chars] + f"\n…(+{len(rendered) - max_chars} chars — render truncation; trajectory incomplete)"


def _render_call(name: str, source: str, args_trunc: int) -> str:
    """`tools.exec_command({...})` -> `[ACTION] shell: <cmd>`, `tools.view_image({...})` -> `[ACTION] view_image: <path>`."""
    # Batched image calls can put a long path array before a non-JSON argument
    # such as {path}. Keep that whole program: clipping can remove the view call
    # and its last paths even though the following observation contains images.
    fallback_limit = 0 if re.search(r"\btools\.view_image\s*\(", source) else args_trunc
    fallback = f"[ACTION] {name}: {_clip(source, fallback_limit)}"
    decoder = json.JSONDecoder()
    parsed = []
    for match in _TOOL_CALL.finditer(source):
        try:
            # Decode one argument object at a time: a greedy regex merges batched calls,
            # including later image views, into the first command's arguments.
            args, end = decoder.raw_decode(source, match.end())
        except json.JSONDecodeError:
            return fallback  # Non-JSON JavaScript stays visible without being evaluated.
        parsed.append((match.group(1), source[match.end():end], args))
    if not parsed:
        try:
            parsed.append((name.rsplit(".", 1)[-1], source, json.loads(source)))
        except json.JSONDecodeError:
            return fallback
    calls = []
    for tool, args_text, args in parsed:
        if not isinstance(args, dict):
            return fallback
        if tool == "exec_command" and "cmd" in args:
            calls.append(f"[ACTION] shell: {_clip(args['cmd'], args_trunc)}")
        elif tool == "view_image" and "path" in args:
            calls.append(f"[ACTION] view_image: {args['path']}")
        else:
            calls.append(f"[ACTION] {tool}: {_clip(args_text, args_trunc)}")
    return "\n".join(calls)


class CodexProposer(Proposer):
    """harness2's Proposer (cache, retries, audit trail, harvest of context/harness) with Codex as the session runner."""

    def _opencode(self, cwd: Path, mission: str, system: str, wall: int) -> tuple[str, float, str]:
        (cwd / "MISSION.md").write_text((f"{system}\n\n---\n\n" if system else "") + mission, encoding="utf-8")
        (cwd / "output").mkdir(exist_ok=True)
        prompt = ("Read MISSION.md first. Do what it asks. Reply with the requested output as "
                  "your final message AND save it verbatim to output/answer.md.")
        stream, last = cwd / ".codex-stream.jsonl", cwd / ".codex-last.txt"
        done = codex_exec(cwd, prompt, stream=stream, last=last, timeout=wall)
        if self.audit_dir:  # keep the improver's own session next to harness2's audit files
            keep = Path(self.audit_dir) / "codex-sessions"
            keep.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stream, keep / f"{int(time.time() * 1000)}.jsonl")
        answer = cwd / "output" / "answer.md"
        if answer.is_file() and answer.read_text(errors="replace").strip():
            return answer.read_text(errors="replace"), 0.0, ""
        text = last.read_text(errors="replace") if last.is_file() else final_message(stream)
        if text.strip():
            return text, 0.0, ""
        return "", 0.0, f"rc={done.returncode}: {(done.stderr or '')[-300:]}"


class CodexAdapter:
    """Tasks come from `<root>/world/tasks.json`: [{id, node, domain, project, label}], `project` an absolute path."""

    def __init__(self, root: Path, *, simulate_before_rule: bool = False, timeout: int = 3600, base_url: str = BASE_URL):
        self.root = Path(root)
        self.substrate = CodexSubstrate()
        channel = ChannelSpec("opencode", "codex/default", timeout=timeout)
        self.spec = BenchSpec(
            name="aicheck-node-audit",
            runs_root=self.root / "runs",
            install_mode="codex_root",
            prompts=BenchPrompts(
                work="audit one engineering node of a pressure-pipeline inspection project against that node's "
                     "rules, and report every atomic check with a conclusion and page-level evidence",
                deliverable_word="audit report",
                domain_guidance=FOLD_NOTE,
            ),
            channels={"proposer": channel, "selector": channel},
            leak_globs=("gold*", "*.gold.json"),
        )
        self.timeout = timeout
        self.base_url = base_url
        self._tasks = {t["id"]: t for t in json.loads((self.root / "world" / "tasks.json").read_text(encoding="utf-8"))}
        self._gold: dict[str, Path] = {}
        base = ST.export_tree(SKILL_SRC, "codex")
        if simulate_before_rule:
            base[SKILL_MD] = "".join(line for line in base[SKILL_MD].splitlines(keepends=True) if RULE_MARK not in line)
        if not self.base_harness().is_dir():
            tree.write_tree(self.substrate.surface(), base, self.base_harness(), stubs=False)

    # -- the adapter protocol ------------------------------------------------------------------
    def tasks(self, split: str = "all") -> list[str]:
        return sorted(self._tasks)

    def domain_of(self, task_id: str) -> str:
        return self._tasks[task_id]["domain"]

    def task_prompt(self, task_id: str) -> str:
        return self._prompt(task_id, Path("<workspace>"), Path("<run>"))

    def task_files(self, task_id: str) -> Path:
        return Path(self._tasks[task_id]["project"])

    def base_harness(self) -> Path:
        return self.root / "base"

    def validate_tree(self, harness: tree.Tree) -> None:
        problems = ST.check_tree(harness, expected_references=ST.reference_names(SKILL_SRC), layout="codex")
        if problems:
            raise ValueError(" | ".join(problems))

    def execute(self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None) -> Path:
        run_dir = self.root / "executions" / run_id
        if (run_dir / ".complete").is_file():
            return run_dir
        shutil.rmtree(run_dir, ignore_errors=True)
        ws = run_dir / "ws"
        self.install(Path(harness_dir) if harness_dir else self.base_harness(), ws)
        (run_dir / "home").mkdir()
        env = {**os.environ, "AICHECK_AUDIT_HOME": str(run_dir / "home"), "AICHECK_REPO": str(REPO),
               "AICHECK_ALLOW_HTTP": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        if self.base_url:
            env["AICHECK_BASE_URL"] = self.base_url
        started = time.time()
        done = codex_exec(ws, self._prompt(task_id, ws, run_dir), stream=run_dir / "stream.jsonl",
                          last=run_dir / "last.txt", timeout=timeout or self.timeout,
                          add_dirs=(run_dir, self.task_files(task_id)), network=True, env=env, ephemeral=False)
        rollout = find_rollout(run_dir / "stream.jsonl")
        if rollout:  # the only record of the auditor's image views
            shutil.copy2(rollout, run_dir / "rollout.jsonl")
        meta = {"returncode": done.returncode, "wall_s": round(time.time() - started, 1), "rollout": bool(rollout),
                "stderr_tail": (done.stderr or "")[-2000:], **usage_of(run_dir / "stream.jsonl")}
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        if self.delivered(run_dir):
            (run_dir / ".complete").write_text("ok", encoding="utf-8")
        return run_dir

    def delivered(self, run_dir: Path) -> bool:
        return (run_dir / "bundle" / "audit.md").is_file()

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        if (run_dir / "rollout.jsonl").is_file():
            return render_rollout(run_dir / "rollout.jsonl", obs_trunc=obs_trunc, max_chars=400_000)
        return ("[HARNESS] no session rollout was kept for this run, so image views are not shown below\n"
                + self.substrate.read_trajectory(run_dir / "stream.jsonl", obs_trunc=obs_trunc, max_chars=400_000))

    def deliverable_text(self, run_dir: Path) -> str:
        return (run_dir / "bundle" / "audit.md").read_text(encoding="utf-8")

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        return {"audit.md": self.deliverable_text(run_dir)}

    def score(self, run_dir: Path, task_id: str) -> dict | None:
        """The after-the-fact judge: eval/score.py against the gold answer given to `set_gold`. Never called in the loop."""
        if task_id not in self._gold:
            raise RuntimeError("no gold answer for this task; the judge calls set_gold after the loop")
        got = _load_score().score(json.loads(self._gold[task_id].read_text(encoding="utf-8")), Path(run_dir) / "bundle")
        return {"n_passed": round(got["points"] * 2), "n_criteria": round(got["max"] * 2),
                "all_pass": got["all_pass"], "percent": got["percent"], "critical": got["critical"],
                "standardEvidence": got["standardEvidence"], "scoreSchemaVersion": got["schemaVersion"]}

    def set_gold(self, gold: dict[str, Path]) -> None:
        self._gold = {task: Path(path) for task, path in gold.items()}

    # -- the solver's workspace -------------------------------------------------------------------
    @staticmethod
    def install(harness: Path, ws: Path) -> None:
        """Lay a harness tree out as the auditor sees it: the skill unfolded, everything else as the tree has it."""
        files = ST.read_tree_dir(harness)
        skill_dir = ws / "skills" / ST.NAME
        ST.import_tree(files, skill_dir, layout="codex")
        prefix = str(Path(SKILL_MD).parent) + "/"
        ST.write_tree_dir({rel: text for rel, text in files.items() if not rel.startswith(prefix)}, ws)
        (ws / ".agents" / "skills").mkdir(parents=True, exist_ok=True)
        (ws / ".agents" / "skills" / ST.NAME).symlink_to(Path("..") / ".." / "skills" / ST.NAME)
        (ws / "backend").mkdir()
        (ws / "backend" / ".venv").symlink_to(Path(TOOL_PYTHON).absolute().parents[1])
        # The auditor treats the workspace as the repo: what the skill says lives there must be found there too.
        (ws / "backend" / "business_packs").symlink_to(REPO / "backend" / "business_packs")
        (ws / "rules").symlink_to(REPO / "rules")

    def _prompt(self, task_id: str, ws: Path, run_dir: Path) -> str:
        t = self._tasks[task_id]
        return PROMPT_TEMPLATE.read_text(encoding="utf-8").format(
            repo=ws, project_dir=t["project"], node=f"{int(t['node']):02d}", project_label=t["label"],
            out_dir=run_dir / "bundle", run_home=run_dir / "home", base_url=self.base_url or "<server>",
            python="backend/.venv/bin/python")
