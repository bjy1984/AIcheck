"""Trial isolation: hide, hand over a copy, archive, restore, scan. Everything in a temp home; no project data."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ISOLATE = Path(__file__).resolve().parents[1] / "eval/isolate.py"
spec = importlib.util.spec_from_file_location("isolate_under_test", ISOLATE)
iso = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iso)

FULL_ID = "110101199001011237"  # 合成号码：出生日期合法、校验位正确
MASKED = "1101**********1237"


class IsolateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        audit = self.home / ".aicheck-node-audit"
        (audit / "eval/gold").mkdir(parents=True)
        (audit / "eval/gold/answers.json").write_text('{"secret": true}', encoding="utf-8")
        self.project = Path(self.tmp.name) / "项目甲"
        (self.project / "合同").mkdir(parents=True)
        (self.project / "合同/合同.txt").write_text("计划施工时间 2026-03-25", encoding="utf-8")
        self.repo = Path(self.tmp.name) / "repo"  # 试跑者工作的仓库：测试里用临时的，不碰真仓库
        self.repo.mkdir()
        if shutil.which("git"):
            subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        (self.repo / "existing.txt").write_text("早就在", encoding="utf-8")

    def prep(self, tag="t1", *extra):
        return self.run_cli("prepare", "--tag", tag, "--project", str(self.project), "--repo", str(self.repo), *extra)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv: str) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = iso.main(["--home", str(self.home), *argv])
        return code, json.loads(out.getvalue())

    def test_prepare_hides_audit_home_and_gives_a_private_copy(self):
        code, out = self.prep()
        self.assertEqual(code, 0, out)
        data = out["data"]
        self.assertFalse((self.home / ".aicheck-node-audit").exists())  # 标准答案所在的目录被挪走
        self.assertTrue((self.home / ".aicheck-node-audit.hold/eval/gold/answers.json").is_file())
        copy = Path(data["projectDir"])
        self.assertEqual(copy.name, "项目甲")
        self.assertEqual((copy / "合同/合同.txt").read_text(encoding="utf-8"), "计划施工时间 2026-03-25")
        self.assertTrue(Path(data["runsDir"]).is_dir())
        self.assertEqual(data["env"], {"AICHECK_AUDIT_HOME": str(self.home / ".aicheck-node-audit-t1")})
        self.assertEqual(stat.S_IMODE(copy.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((copy / "合同/合同.txt").stat().st_mode), 0o600)
        # 没还原就再 prepare：拒绝，不覆盖
        code, out = self.prep("t2")
        self.assertEqual((code, out["error"]["code"]), (1, "holdExists"))
        self.assertEqual(self.run_cli("status")[1]["data"]["hiddenPresent"], True)

    def test_project_inside_the_audit_home_is_copied_before_it_is_hidden(self):
        inside = self.home / ".aicheck-node-audit/eval/runs/r1/projects/项目乙"
        inside.mkdir(parents=True)
        (inside / "a.txt").write_text("x", encoding="utf-8")
        code, out = self.run_cli("prepare", "--tag", "t1", "--project", str(inside), "--repo", str(self.repo))
        self.assertEqual(code, 0, out)
        self.assertTrue((Path(out["data"]["projectDir"]) / "a.txt").is_file())

    def test_finish_archives_checks_ids_and_restores(self):
        data = self.prep()[1]["data"]
        bundle = Path(data["runsDir"]) / "codex-node-24"
        (bundle / "files").mkdir(parents=True)
        (bundle / "files/原件.txt").write_text(f"身份证 {FULL_ID}", encoding="utf-8")  # 原件里有号码不算
        (bundle / "audit.md").write_text(f"检查：\n{FULL_ID}\n", encoding="utf-8")
        (bundle / "digest.md").write_text(f"身份证 {MASKED}", encoding="utf-8")
        code, out = self.run_cli("finish", "--tag", "t1")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["stashed"], ["codex-node-24"])
        self.assertEqual(out["data"]["fullIdNumbersFound"], {"runs/codex-node-24/audit.md": 1})  # 只报报告里的
        self.assertFalse((self.home / ".aicheck-node-audit.hold").exists())
        self.assertTrue((self.home / ".aicheck-node-audit/eval/gold/answers.json").is_file())  # 答案回来了
        self.assertTrue((self.home / ".aicheck-node-audit/eval/runs/t1/runs/codex-node-24/audit.md").is_file())
        self.assertFalse((self.home / ".aicheck-node-audit-t1").exists())  # 试跑者的副本删掉
        self.assertTrue(self.project.is_dir())  # 原项目目录不动

    def test_finish_keeps_stray_files_and_refuses_when_not_prepared(self):
        self.assertEqual(self.run_cli("finish", "--tag", "t1")[1]["error"]["code"], "notPrepared")
        data = self.prep()[1]["data"]
        (Path(data["runHome"]) / "notes.txt").write_text("试跑者顺手写的", encoding="utf-8")
        (Path(data["runsDir"]) / "pages.json").write_text("{}", encoding="utf-8")
        out = self.run_cli("finish", "--tag", "t1")[1]["data"]
        self.assertEqual(out["strayFiles"], ["notes.txt"])
        self.assertIn("pages.json", out["stashed"])
        self.assertTrue((self.home / ".aicheck-node-audit/eval/runs/t1/stray/run-home/notes.txt").is_file())

    @unittest.skipUnless(shutil.which("git"), "需要 git")
    def test_stash_between_nodes_reports_and_moves_files_left_behind(self):
        watched = Path(self.tmp.name) / "scratch"
        watched.mkdir()
        (watched / "old.txt").write_text("早就在", encoding="utf-8")
        data = self.prep("t1", "--watch", str(watched))[1]["data"]
        runs = Path(data["runsDir"])
        (runs / "codex-node-24").mkdir()
        (runs / "codex-node-24/audit.md").write_text("第一个节点的结论", encoding="utf-8")
        (self.repo / "fill_audit.py").write_text("answers = ...", encoding="utf-8")  # 执行者留下的脚本
        (watched / "tmp1.json").write_text("{}", encoding="utf-8")
        code, out = self.run_cli("stash", "--tag", "t1")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["stashed"], ["codex-node-24"])
        self.assertEqual(out["data"]["newInRepo"], {"fill_audit.py": "??"})  # 早就在的 existing.txt 不算
        self.assertEqual(out["data"]["newInWatched"], {str(watched.resolve()): ["tmp1.json"]})
        self.assertEqual(out["data"]["movedStray"], [])
        self.assertTrue((self.repo / "fill_audit.py").is_file())  # 没加 --move-stray 就只报告
        self.assertEqual(list(runs.iterdir()), [])  # 下一个节点的执行者看不到上一个的结果
        # 第二个节点：同名资料包不能覆盖归档；加 --move-stray 把新文件移走
        (runs / "codex-node-24").mkdir()
        code, out = self.run_cli("stash", "--tag", "t1", "--move-stray")
        self.assertEqual((code, out["error"]["code"]), (1, "archiveExists"))
        shutil.rmtree(runs / "codex-node-24")
        (runs / "codex-node-25").mkdir()
        (self.repo / "other_session.py").write_text("别的会话刚建的", encoding="utf-8")
        code, out = self.run_cli("stash", "--tag", "t1", "--move-stray")
        self.assertEqual(code, 0, out)
        # --move-stray 只移 --watch 目录里的：仓库里新冒出的分不出是谁建的（c 轮评测误移过别的会话 138 个文件）
        self.assertEqual(out["data"]["movedStray"], [f"{watched.resolve()}:tmp1.json"])
        self.assertTrue((self.repo / "fill_audit.py").is_file())
        self.assertEqual(self.run_cli("stash", "--tag", "t1", "--move-repo", "existing.txt")[1]["error"]["code"], "notStray")
        code, out = self.run_cli("stash", "--tag", "t1", "--move-repo", "fill_audit.py")  # 看过 newInRepo，点名移走执行者留下的
        self.assertEqual((code, out["data"]["movedStray"]), (0, ["repo:fill_audit.py"]), out)
        self.assertFalse((self.repo / "fill_audit.py").exists())
        self.assertTrue((self.repo / "other_session.py").is_file())
        self.assertTrue((self.repo / "existing.txt").is_file())
        self.assertTrue((watched / "old.txt").is_file())
        archive = self.home / ".aicheck-node-audit.hold/eval/runs/t1"
        self.assertEqual((archive / "stray/repo/fill_audit.py").read_text(encoding="utf-8"), "answers = ...")
        self.assertTrue((archive / "runs/codex-node-24/audit.md").is_file())
        self.assertEqual(self.run_cli("finish", "--tag", "t1")[0], 0)

    def test_prompt_is_rendered_and_never_mentions_where_answers_live(self):
        data = self.prep()[1]["data"]
        code, out = self.run_cli("prompt", "--tag", "t1", "--node", "4", "--project-dir", data["projectDir"],
                                 "--base-url", "http://server.example:8081", "--repo", "/work/repo")
        self.assertEqual(code, 0, out)
        text = out["data"]["prompt"]
        run_home = str(self.home / ".aicheck-node-audit-t1")
        self.assertEqual(out["data"]["outDir"], f"{run_home}/runs/codex-项目甲-node-04")
        for expected in ("/work/repo", data["projectDir"], "节点：04", "项目标签：TEST-项目甲", f"--out {out['data']['outDir']}",
                         f"AICHECK_AUDIT_HOME={run_home}", "AICHECK_BASE_URL=http://server.example:8081", "backend/.venv/bin/python"):
            self.assertIn(expected, text)
        self.assertNotRegex(text, r"\{[a-z_]+\}")  # 没有漏填的占位符
        self.assertIn("无法看图", text)  # 看不了图就停，不能硬做
        for pattern in iso.LEAK_PATTERNS.values():  # 提示词本身不能带答案所在的路径：否则 scan 里分不清
            self.assertIsNone(re.search(pattern, text), pattern)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            iso.main(["--home", str(self.home), "prompt", "--tag", "t1", "--node", "4", "--project-dir", data["projectDir"],
                      "--base-url", "http://server.example:8081", "--raw"])
        self.assertTrue(out.getvalue().startswith("请在仓库"))

    def test_scan_skips_lines_the_harness_wrote_but_not_the_runners_own(self):
        transcript = Path(self.tmp.name) / "claude.jsonl"
        transcript.write_text("\n".join([
            json.dumps({"agentId": "a1", "attachment": {"type": "instructions", "files": [{"path": "/home/x/memory/MEMORY.md"}]}}),
            json.dumps({"type": "api-request-blob", "hash": "h", "text": "see claude.ai/artifact/AbC and ~/.aicheck-node-audit.hold/eval/gold"}),
            json.dumps({"type": "api-request-shape", "shapeHash": "s", "text": "/memory/"}),
            json.dumps({"attachment": {"type": "prompt_snapshot", "systemPrompt": "... /memory/ ..."}}),
            json.dumps({"message": {"content": [{"type": "tool_use", "input": {"command": "cat ~/.aicheck-node-audit.hold/eval/gold/x.json"}}]}}),
            "plain text mentioning /memory/ is still scanned",
        ]), encoding="utf-8")
        code, out = self.run_cli("scan", "--tag", "t1", str(transcript))
        self.assertEqual(code, 0, out)
        [report] = out["data"]["files"]
        self.assertEqual(report["harnessLinesSkipped"], 4)
        self.assertEqual(report["peeks"]["标准答案目录"]["count"], 1)  # 执行者自己的命令照样被抓
        self.assertEqual(report["peeks"]["被藏起来的目录"]["count"], 1)
        self.assertEqual(report["peeks"]["记忆文件"]["count"], 1)  # 非 JSON 的普通行也照样扫
        self.assertNotIn("评估文档", report["peeks"])  # 注入行里的评估文档地址不算

    def test_bad_tag_and_missing_project(self):
        self.assertEqual(self.prep("../x")[1]["error"]["code"], "invalidTag")
        self.assertEqual(self.run_cli("prepare", "--tag", "t1", "--project", str(self.home / "nope"), "--repo", str(self.repo))[1]["error"]["code"], "projectMissing")
        self.assertTrue((self.home / ".aicheck-node-audit").is_dir())  # 失败不动目录

    def test_scan_flags_peeks_pdf_reads_and_full_ids(self):
        transcript = Path(self.tmp.name) / "session.jsonl"
        transcript.write_text("\n".join([
            '{"cmd": "ls ~/.aicheck-node-audit.hold/eval/gold"}',
            '{"cmd": "cat ~/.aicheck-node-audit-t1/runs/x/audit.md"}',
            '{"cmd": "ls ~/.aicheck-node-audit-t0/runs"}',
            '{"cmd": "python -c \\"import fitz; fitz.open(\'a.pdf\')\\""}',
            json.dumps({"out": f"姓名：\n{FULL_ID}\n"}),  # JSON 转义后的换行紧挨号码
            json.dumps({"out": f"身份证 {MASKED}"}),
            '{"cmd": "Read /Users/x/Documents/notes.txt"}',
        ]), encoding="utf-8")
        code, out = self.run_cli("scan", "--tag", "t1", str(transcript))
        self.assertEqual(code, 0, out)
        [report] = out["data"]["files"]
        self.assertEqual(report["peeks"]["标准答案目录"]["count"], 1)
        self.assertEqual(report["peeks"]["被藏起来的目录"]["count"], 1)
        self.assertEqual(report["peeks"]["别的试跑目录"]["count"], 1)  # t1 自己的不算
        self.assertEqual(report["fullIdNumberLines"]["count"], 1)  # 脱敏号不算
        self.assertNotIn(FULL_ID, json.dumps(out, ensure_ascii=False))  # 扫描输出本身不带完整号码
        self.assertEqual(report["directPdfReads"]["count"], 1)
        self.assertEqual(self.run_cli("scan", str(self.home / "none"))[1]["error"]["code"], "fileNotFound")


if __name__ == "__main__":
    unittest.main()
