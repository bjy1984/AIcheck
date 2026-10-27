"""The harness2 adapter skeleton. Needs a harness2 checkout (HARNESS2_SRC) and Python 3.12 or 3.13; skipped otherwise."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
ADAPTER_DIR = DEV / "harness2_adapter"
H2 = os.environ.get("HARNESS2_SRC", "")
PY = shutil.which("python3.12") or shutil.which("python3.13")
NEED = unittest.skipUnless(H2 and (Path(H2) / "harness2").is_dir() and PY, "set HARNESS2_SRC to a harness2 checkout and have python3.12/3.13")


def run_py(args: list[str], timeout: int = 280) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": H2, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([PY, *args], capture_output=True, text=True, env=env, timeout=timeout, check=False)


@NEED
class Harness2AdapterTest(unittest.TestCase):
    def test_skeleton_runs_the_whole_workflow_and_judges_after_the_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = run_py([str(ADAPTER_DIR / "run_skeleton.py"), "--out", tmp, "--k", "1", "--reject-first"])
            self.assertEqual(done.returncode, 0, done.stdout[-1500:] + done.stderr[-1500:])
            out = done.stdout
            self.assertIn("2 tasks done, 0 failed", out)
            self.assertEqual(out.count("chosen=adapted  28/28 points (100.0%)"), 4)  # 两个任务 × 两种模式
            self.assertEqual(out.count("base    26/28 points (92.9%)"), 2)  # 基线把条件句判成不适用，扣 2 个半分
            self.assertIn("files that differ from the live skill: ['SKILL.md']", out)
            adopted = sorted(Path(tmp, "library").rglob("harnesses/*/harness"))
            self.assertTrue(adopted)
            self.assertFalse(Path(adopted[0], "references").exists())  # 库里的 harness 没有范围外的文件
            self.assertTrue(Path(tmp, "back-to-skill", "references", "audit-method.md").is_file())

    def test_validation_rejects_dropped_frozen_parts_and_off_surface_files(self):
        code = f"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, {str(ADAPTER_DIR)!r})
from aicheck_h2 import AicheckAdapter, SCRIPT, SKILL_MD
from harness2.core import tree
import run_skeleton as R
root = Path(tempfile.mkdtemp()); R.build_world(root)
ad = AicheckAdapter(root); surface = ad.substrate.surface()
good = tree.read_tree(surface, ad.base_harness())
tree.validate(surface, good); ad.validate_tree(good); print('GOOD')
try: ad.validate_tree({{**good, SCRIPT: good[SCRIPT].replace('def mask_value', 'def x')}})
except ValueError as e: print('FROZEN', e)
try: ad.validate_tree({{**good, SKILL_MD: good[SKILL_MD].replace('<!-- folded from references/tools.md -->', '')}})
except ValueError as e: print('MARKER', e)
extra = root / 'base' / 'references'; extra.mkdir(); (extra / 'x.md').write_text('x')
rejected = []; tree.read_tree(surface, root / 'base', rejected=rejected); print('REJECTED', rejected)
"""
        done = run_py(["-c", code], timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-1500:])
        self.assertIn("GOOD", done.stdout)
        self.assertRegex(done.stdout, r"FROZEN .*def mask_value")
        self.assertRegex(done.stdout, r"MARKER .*tools\.md")
        self.assertIn("REJECTED ['references/x.md']", done.stdout)  # harness2 自己把 references/ 当范围外


if __name__ == "__main__":
    unittest.main()
