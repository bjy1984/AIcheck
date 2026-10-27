"""Fold/unfold of the skill's references and the export/import of a harness tree; no harness2, no model."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
REAL_SKILL = DEV.parent / "aicheck-node-audit"
spec = importlib.util.spec_from_file_location("skill_tree_under_test", DEV / "harness2_adapter/skill_tree.py")
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)

SCRIPT_TEXT = "def mask_value(v):\n    return v\n\n\ndef is_id_number(v):\n    return False\n\n\ndef check_report(r):\n    return []\n"


def make_skill(root: Path) -> Path:
    (root / "references").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "SKILL.md").write_text("---\nname: aicheck-node-audit\ndescription: x\n---\n\n# Skill\n\n---\n\nbody without trailing newline", encoding="utf-8")
    (root / "references" / "audit-method.md").write_text("# Method\n\n---\n\nmore\n", encoding="utf-8")
    (root / "references" / "tools.md").write_text("# Tools\n", encoding="utf-8")
    (root / "scripts" / "node_audit.py").write_text(SCRIPT_TEXT, encoding="utf-8")
    return root


class SkillTreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.skill = make_skill(self.root / "skill")

    def tearDown(self):
        self.tmp.cleanup()

    def test_fold_and_unfold_are_lossless_even_with_horizontal_rules_and_no_trailing_newline(self):
        folded = st.fold(self.skill)
        self.assertIn("<!-- folded from references/audit-method.md -->", folded)
        self.assertLess(folded.index("audit-method.md"), folded.index("tools.md"))  # 固定顺序：按文件名排序
        skill, refs = st.unfold(folded)
        self.assertEqual(skill, (self.skill / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(refs, {"audit-method.md": "# Method\n\n---\n\nmore\n", "tools.md": "# Tools\n"})

    def test_refold_is_the_same_layout_fold_writes(self):
        skill, refs = st.unfold(st.fold(self.skill))
        self.assertEqual(st.refold(skill, refs), st.fold(self.skill))

    def test_real_skill_survives_the_round_trip(self):
        skill, refs = st.unfold(st.fold(REAL_SKILL))
        self.assertEqual(skill, (REAL_SKILL / "SKILL.md").read_text(encoding="utf-8"))
        names = st.reference_names(REAL_SKILL)
        self.assertGreaterEqual(len(names), 4)
        for name in names:
            self.assertEqual(refs[name], (REAL_SKILL / "references" / name).read_text(encoding="utf-8"), name)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = st.main(["roundtrip", "--skill-dir", str(REAL_SKILL)])
        self.assertEqual((code, json.loads(out.getvalue())["data"]["lossless"]), (0, True))

    def test_export_has_only_files_on_the_editable_surface(self):
        tree = st.export_tree(self.skill)
        self.assertEqual(sorted(tree), sorted([*st.ALWAYS_ON, st.SKILL_MD, st.SCRIPT]))  # 没有 references/ 目录
        self.assertIn("aicheck-node-audit", tree["guardrails.md"])  # harness2 要求 skill 名出现在常开文本里
        self.assertEqual(st.check_tree(tree, expected_references=st.reference_names(self.skill)), [])

    def test_codex_layout_round_trips_through_its_own_paths(self):
        cx = st.LAYOUTS["codex"]
        tree = st.export_tree(self.skill, "codex")
        self.assertEqual(sorted(tree), sorted([*cx["always_on"], cx["skill_md"], cx["script"]]))
        self.assertIn(".agents/skills/aicheck-node-audit/SKILL.md", tree["AGENTS.md"])  # Codex 的触发行
        self.assertEqual(st.check_tree(tree, expected_references=st.reference_names(self.skill), layout="codex"), [])
        self.assertIn("missing", " ".join(st.check_tree(tree)))  # 按 opencode 路径找不到 SKILL.md
        report = st.import_tree(tree, self.root / "cx-out", base_skill_dir=self.skill, layout="codex")
        self.assertEqual((report["changed"], report["harnessOnlyChanged"]), ([], []))

    def test_check_tree_blocks_what_must_stay(self):
        tree = st.export_tree(self.skill)
        no_mask = {**tree, st.SCRIPT: tree[st.SCRIPT].replace("def mask_value", "def renamed")}
        self.assertIn("def mask_value", " ".join(st.check_tree(no_mask)))
        lost_ref = {**tree, st.SKILL_MD: tree[st.SKILL_MD].replace("<!-- folded from references/tools.md -->", "")}
        self.assertIn("tools.md", " ".join(st.check_tree(lost_ref, expected_references=["audit-method.md", "tools.md"])))
        doubled = {**tree, st.SKILL_MD: tree[st.SKILL_MD] + st.fold(self.skill)[len((self.skill / "SKILL.md").read_text(encoding="utf-8")):]}
        self.assertIn("twice", " ".join(st.check_tree(doubled)))
        self.assertIn("missing", " ".join(st.check_tree({k: v for k, v in tree.items() if k != st.SKILL_MD})))

    def test_import_writes_a_new_directory_and_reports_the_changes(self):
        tree = st.export_tree(self.skill)
        skill_text, refs = st.unfold(tree[st.SKILL_MD])
        refs["tools.md"] += "\nadded line\n"
        edited = {**tree, "guardrails.md": tree["guardrails.md"] + "- extra\n",
                  st.SKILL_MD: st.refold(skill_text, refs)}
        before = {p: p.read_bytes() for p in self.skill.rglob("*") if p.is_file()}
        report = st.import_tree(edited, self.root / "out", base_skill_dir=self.skill)
        self.assertEqual(report["changed"], ["references/tools.md"])
        self.assertEqual(report["harnessOnlyChanged"], ["guardrails.md"])  # 没有对应的 skill 文件，交人决定
        self.assertEqual((self.root / "out/references/tools.md").read_text(encoding="utf-8"), "# Tools\n\nadded line\n")
        self.assertEqual((self.root / "out/SKILL.md").read_text(encoding="utf-8"), (self.skill / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(before, {p: p.read_bytes() for p in self.skill.rglob("*") if p.is_file()})  # 原 skill 一个字节都没动
        with self.assertRaises(st.SkillTreeError):  # 目标已存在就拒绝
            st.import_tree(edited, self.root / "out", base_skill_dir=self.skill)

    def test_import_refuses_a_tree_that_dropped_the_frozen_parts(self):
        tree = st.export_tree(self.skill)
        bad = {**tree, st.SCRIPT: "print('hi')\n"}
        with self.assertRaises(st.SkillTreeError) as ctx:
            st.import_tree(bad, self.root / "out2", base_skill_dir=self.skill)
        self.assertIn("frozen", str(ctx.exception))
        self.assertFalse((self.root / "out2").exists())  # 拒绝时不写任何东西

    def test_cli_export_check_import_round(self):
        def run(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = st.main(list(argv))
            return code, json.loads(out.getvalue())
        self.assertEqual(run("export", "--skill-dir", str(self.skill), "--out", str(self.root / "h"))[0], 0)
        self.assertEqual(run("export", "--skill-dir", str(self.skill), "--out", str(self.root / "h"))[0], 1)  # 已存在
        self.assertEqual(run("check", "--harness", str(self.root / "h"), "--skill-dir", str(self.skill))[1]["data"], {"problems": []})
        code, out = run("import", "--harness", str(self.root / "h"), "--out", str(self.root / "back"), "--skill-dir", str(self.skill))
        self.assertEqual((code, out["data"]["changed"]), (0, []))  # 原样导出再导回，没有任何改动


if __name__ == "__main__":
    unittest.main()
