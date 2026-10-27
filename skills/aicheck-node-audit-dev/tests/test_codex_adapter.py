"""The Codex adapter and improver, with a stand-in `codex` binary (no model). Needs HARNESS2_SRC and Python 3.12/3.13."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
ADAPTER_DIR = DEV / "harness2_adapter"
H2 = os.environ.get("HARNESS2_SRC", "")
PY = shutil.which("python3.12") or shutil.which("python3.13")
NEED = unittest.skipUnless(H2 and (Path(H2) / "harness2").is_dir() and PY, "set HARNESS2_SRC to a harness2 checkout and have python3.12/3.13")

# Stands in for `codex exec`: checks the flags the adapter relies on, writes a --json stream and the last message,
# and, as the improver, edits context/harness/AGENTS.md and writes output/answer.md.
FAKE_CODEX = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, sys
    from pathlib import Path
    argv = sys.argv[1:]
    assert argv[0] == "exec" and argv[-1] == "-" and "--json" in argv and "--ignore-user-config" in argv, argv
    cwd = Path(argv[argv.index("-C") + 1]); last = Path(argv[argv.index("-o") + 1]); prompt = sys.stdin.read()
    log = Path(os.environ["FAKE_CODEX_LOG"]); log.open("a").write(json.dumps({"argv": argv, "cwd": str(cwd)}) + "\\n")
    if (cwd / "MISSION.md").is_file():
        (cwd / "context/harness/AGENTS.md").open("a").write("- edited\\n")
        (cwd / "output/answer.md").write_text("<notes>edited</notes>")
        text = "edited"
    else:
        skill = (cwd / "skills/aicheck-node-audit/SKILL.md").read_text()
        refs = sorted(p.name for p in (cwd / "skills/aicheck-node-audit/references").glob("*.md"))
        text = f"skill {len(skill)} refs {refs} same-via-agents {(cwd / '.agents/skills/aicheck-node-audit/SKILL.md').read_text() == skill}"
    print(json.dumps({"type": "thread.started", "thread_id": "tid-123"}))
    print(json.dumps({"type": "item.completed", "item": {"id": "1", "type": "agent_message", "text": text}}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 7, "output_tokens": 3}}))
    last.write_text(text)
    if "--ephemeral" not in argv:  # like Codex: the rollout is the only place an image view is recorded
        day = Path(os.environ["CODEX_HOME"], "sessions/2026/10/23"); day.mkdir(parents=True, exist_ok=True)
        call = 'const r = await tools.view_image({"path":"/ws/bundle/pages/p1.png","detail":"original"});'
        rows = [{"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": call}},
                {"type": "response_item", "payload": {"type": "custom_tool_call_output", "output": [
                    {"type": "input_text", "text": "Script completed"}, {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}]}}]
        (day / "rollout-2026-10-23T12-00-00-tid-123.jsonl").write_text(chr(10).join(json.dumps(r) for r in rows))
""")


@NEED
class CodexAdapterTest(unittest.TestCase):
    def test_judge_keeps_the_evidence_gate_even_at_full_marks(self):
        with tempfile.TemporaryDirectory() as tmp:
            gold = Path(tmp, "synthetic.json")
            gold.write_text("{}")
            code = f"""
import json, sys
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, {str(ADAPTER_DIR)!r})
import codex_h2 as C
from aicheck_h2 import AicheckAdapter
result = {{'points': 10, 'max': 10, 'percent': 100, 'critical': [], 'all_pass': False,
          'standardEvidence': {{'status': 'review_required'}}, 'schemaVersion': 'aicheck-node-audit-score@2'}}
scorer = Mock(); scorer.score.return_value = result
real = C.CodexAdapter.__new__(C.CodexAdapter)
real.set_gold({{'synthetic': Path({str(gold)!r})}})
stand_in = AicheckAdapter.__new__(AicheckAdapter)
stand_in.root = Path({str(gold.parent.parent)!r})
stand_in._tasks = {{'synthetic': {{'gold': {str(gold)!r}}}}}
stand_in._score = scorer
with patch.object(C, '_load_score', return_value=scorer):
    print(json.dumps([real.score(Path({str(gold.parent)!r}), 'synthetic'),
                      stand_in.score(Path({str(gold.parent)!r}), 'synthetic')]))
"""
            env = {**os.environ, "PYTHONPATH": H2, "PYTHONDONTWRITEBYTECODE": "1"}
            done = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=60, check=False)
            self.assertEqual(done.returncode, 0, done.stderr[-1500:])
            for result in json.loads(done.stdout):
                self.assertEqual(result["percent"], 100)
                self.assertFalse(result["all_pass"])
                self.assertEqual(result["standardEvidence"]["status"], "review_required")

    def test_failed_view_and_truncated_observation_do_not_hide_image_delivery_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            failed = [{"type": "function_call", "name": "view_image", "arguments": '{"path":"/missing.png"}'},
                      {"type": "function_call_output", "output": "Error: file not found; exit code 1"}]
            batch = [{"type": "custom_tool_call_output", "output": [
                {"type": "input_text", "text": "long tool output " * 1000},
                *[{"type": "input_image", "image_url": "data:image/png;base64,AAAA"} for _ in range(16)]]}]
            ordered = [{"type": "custom_tool_call_output", "output": [
                {"type": "input_text", "text": "before"}, {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
                {"type": "input_text", "text": "after"}]}]
            for name, payloads in [("failed", failed), ("batch", batch), ("ordered", ordered)]:
                (tmp / name).write_text("\n".join(json.dumps({"type": "response_item", "payload": p}) for p in payloads))
            code = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(ADAPTER_DIR)!r})
import codex_h2 as C
root = Path({str(tmp)!r})
print(json.dumps({{
    'failed': C.render_rollout(root / 'failed', obs_trunc=1000, max_chars=400000),
    'batch': C.render_rollout(root / 'batch', obs_trunc=64, max_chars=400000),
    'whole_clip': C.render_rollout(root / 'batch', obs_trunc=64, max_chars=80),
    'ordered': C.render_rollout(root / 'ordered', obs_trunc=1000, max_chars=400000),
}}))
"""
            env = {**os.environ, "PYTHONPATH": H2, "PYTHONDONTWRITEBYTECODE": "1"}
            done = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=60, check=False)
            self.assertEqual(done.returncode, 0, done.stderr[-1500:])
            rendered = json.loads(done.stdout)
            self.assertIn("[ACTION] view_image: /missing.png", rendered["failed"])
            self.assertIn("Error: file not found", rendered["failed"])
            self.assertNotIn("(image shown to the model)", rendered["failed"])
            self.assertEqual(rendered["batch"].count("(image shown to the model)"), 16)
            self.assertIn("render truncation", rendered["batch"])
            self.assertNotIn("base64", rendered["batch"])
            self.assertIn("trajectory incomplete", rendered["whole_clip"])
            self.assertEqual(rendered["ordered"], "[OBSERVATION] before\n(image shown to the model)\nafter")

    def test_long_image_loop_keeps_its_paths_and_call_in_the_trajectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            rollout = Path(tmp, "rollout.jsonl")
            paths = [f"/synthetic/executions/aicheck-node-audit-cx-agg1/node-02/agg1/bundle/pages/"
                     f"{index:02d}-long-descriptive-engineering-document-name-for-the-visual-review-sheet-p001-008.png"
                     for index in range(16)]
            source = ("const paths = " + json.dumps(paths, indent=2) + ";\n"
                      'const rs = await Promise.all(paths.map(path => tools.view_image({path, detail:"original"})));\n'
                      'for (let i=0; i<rs.length; i++) {text(paths[i]); image(rs[i].image_url);}')
            payloads = [
                {"type": "custom_tool_call", "name": "exec", "input": source},
                {"type": "custom_tool_call_output", "output": [
                    {"type": "input_image", "image_url": "data:image/png;base64,AAAA"} for _ in paths]},
            ]
            rollout.write_text("\n".join(json.dumps({"type": "response_item", "payload": p}) for p in payloads))
            code = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ADAPTER_DIR)!r})
import codex_h2 as C
print(C.render_rollout(Path({str(rollout)!r}), obs_trunc=10000, max_chars=400000))
"""
            env = {**os.environ, "PYTHONPATH": H2, "PYTHONDONTWRITEBYTECODE": "1"}
            done = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=60, check=False)
            self.assertEqual(done.returncode, 0, done.stderr[-1500:])
            self.assertIn(source, done.stdout)
            self.assertEqual(done.stdout.count("(image shown to the model)"), len(paths))
            self.assertNotIn("base64", done.stdout)

    def test_rollout_keeps_each_image_in_batched_and_direct_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            rollout = Path(tmp, "rollout.jsonl")
            shell = json.dumps({"cmd": "printf '%s' '{nested} \\\"quoted\\\"'"})
            image_paths = ["/synthetic/p1.png", "/synthetic/p2.png", "/synthetic/p3.png"]
            source = (f"text(await tools.exec_command({shell}));\n"
                      f"const a = await tools.view_image({json.dumps({'path': image_paths[0]})});\n"
                      f"const b = await tools.view_image({json.dumps({'path': image_paths[1], 'detail': 'original'})});")
            payloads = [
                {"type": "custom_tool_call", "name": "exec", "input": source},
                {"type": "function_call", "name": "view_image", "arguments": json.dumps({"path": image_paths[2]})},
                {"type": "custom_tool_call_output", "output": [
                    {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}]},
                # Non-JSON JavaScript arguments stay visible; rendering must not execute them.
                {"type": "custom_tool_call", "name": "exec", "input": "await tools.view_image({path: pagePath});"},
            ]
            rollout.write_text("\n".join(json.dumps({"type": "response_item", "payload": p}) for p in payloads))
            code = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ADAPTER_DIR)!r})
import codex_h2 as C
print(C.render_rollout(Path({str(rollout)!r}), obs_trunc=10000, max_chars=400000))
"""
            env = {**os.environ, "PYTHONPATH": H2, "PYTHONDONTWRITEBYTECODE": "1"}
            done = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=60, check=False)
            self.assertEqual(done.returncode, 0, done.stderr[-1500:])
            lines = done.stdout.splitlines()
            self.assertIn("[ACTION] shell: " + json.loads(shell)["cmd"], lines)
            for path in image_paths:
                self.assertIn("[ACTION] view_image: " + path, lines)
            self.assertIn("(image shown to the model)", done.stdout)
            self.assertNotIn("base64", done.stdout)
            self.assertIn("await tools.view_image({path: pagePath});", done.stdout)

    def test_solver_workspace_and_improver_with_a_stand_in_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fake = tmp / "codex"
            fake.write_text(FAKE_CODEX)
            fake.chmod(0o755)
            (tmp / "project").mkdir()
            (tmp / "root/world").mkdir(parents=True)
            (tmp / "root/world/tasks.json").write_text(
                f'[{{"id": "node-02", "node": 2, "domain": "d", "project": "{tmp / "project"}", "label": "TEST"}}]')
            code = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(ADAPTER_DIR)!r})
import codex_h2 as C
from harness2.core import tree
from harness2.core.spec import ChannelSpec
ad = C.CodexAdapter(Path({str(tmp / "root")!r}), base_url="http://server.example:8081")
surface = ad.substrate.surface()
base = tree.read_tree(surface, ad.base_harness()); tree.validate(surface, base); ad.validate_tree(base)
rd = ad.execute("node-02", None, "base1")
print("DELIVERED", ad.delivered(rd))
print("TRAJ", ad.trajectory(rd, obs_trunc=10000).replace(chr(10), " | "))
print("META", json.loads((rd / "meta.json").read_text())["input_tokens"])
prop = C.CodexProposer(ChannelSpec("opencode", "codex/default", timeout=60), audit_dir=Path({str(tmp / "audit")!r}))
ctx = Path({str(tmp / "ctx")!r}); tree.write_tree(surface, base, ctx / "harness", stubs=False)
r = prop.call("edit the harness", ctx, "inv1.a1", harvest="context/harness")
print("REPLY", r.text, (r.workspace / "AGENTS.md").read_text().endswith("- edited\\n"))
try: ad.score(rd, "node-02")
except RuntimeError as e: print("NOGOLD", e)
"""
            env = {**os.environ, "PYTHONPATH": H2, "PYTHONDONTWRITEBYTECODE": "1", "AICHECK_H2_CODEX": str(fake),
                   "FAKE_CODEX_LOG": str(tmp / "calls.jsonl"), "CODEX_HOME": str(tmp / "codex-home")}
            done = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=120, check=False)
            self.assertEqual(done.returncode, 0, done.stdout[-1500:] + done.stderr[-1500:])
            out = done.stdout
            self.assertIn("DELIVERED False", out)  # 替身不写 audit.md
            # 执行者的轨迹取自 rollout：看图动作要让改进者看得到，图片本身只留占位
            self.assertIn("TRAJ [ACTION] view_image: /ws/bundle/pages/p1.png | [OBSERVATION] Script completed | (image shown to the model)", out)
            self.assertNotIn("base64", out)
            stream = (tmp / "root/executions/base1/stream.jsonl").read_text()
            self.assertRegex(stream, r"refs \['audit-method.md', 'report-format.md', 'standard-pages.md', 'tools.md'\] same-via-agents True")
            self.assertIn("META 7", out)
            self.assertIn("REPLY <notes>edited</notes> True", out)
            self.assertIn("NOGOLD", out)  # 循环里拿不到标准答案
            calls = [__import__("json").loads(line) for line in (tmp / "calls.jsonl").read_text().splitlines()]
            solver, improver = calls
            self.assertIn("sandbox_workspace_write.network_access=true", solver["argv"])  # 执行者要连服务器
            self.assertIn(str(tmp / "project"), solver["argv"])  # 项目目录经 --add-dir 给到
            self.assertNotIn("sandbox_workspace_write.network_access=true", improver["argv"])  # 改进者不联网
            self.assertNotIn("--ephemeral", solver["argv"])  # 执行者留 rollout
            self.assertIn("--ephemeral", improver["argv"])
            self.assertTrue((tmp / "root/executions/base1/rollout.jsonl").is_file())
            self.assertTrue((tmp / "root/executions/base1/ws/backend/.venv").is_symlink())


    def test_rollout_without_a_thread_id_falls_back_to_the_stream_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp, "run")
            run_dir.mkdir()
            (run_dir / "stream.jsonl").write_text('{"type": "item.completed", "item": {"id": "1", "type": "agent_message", "text": "hi"}}\n')
            code = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ADAPTER_DIR)!r})
import codex_h2 as C
run_dir = Path({str(run_dir)!r})
print("FOUND", C.find_rollout(run_dir / "stream.jsonl", wait_s=0))
print(C.CodexAdapter.trajectory(type("A", (), {{"substrate": C.CodexSubstrate()}})(), run_dir, obs_trunc=10000))
"""
            env = {**os.environ, "PYTHONPATH": H2, "PYTHONDONTWRITEBYTECODE": "1"}
            done = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=60, check=False)
            self.assertEqual(done.returncode, 0, done.stderr[-1500:])
            self.assertIn("FOUND None", done.stdout)
            self.assertIn("image views are not shown", done.stdout)  # 改进者被告知缺了看图记录
            self.assertIn("[ASSISTANT] hi", done.stdout)


if __name__ == "__main__":
    unittest.main()
