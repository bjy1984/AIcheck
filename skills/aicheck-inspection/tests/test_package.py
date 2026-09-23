import ast
import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "skills/aicheck-inspection"


class PackageTests(unittest.TestCase):
    def test_round_trip_without_repository_or_credentials(self):
        with tempfile.TemporaryDirectory(prefix="aicheck skill ") as folder:
            archive_path = Path(folder) / "inspection.zip"
            subprocess.run([sys.executable, str(ROOT / "scripts/package_inspection_skill.py"), "--output", str(archive_path)],
                           check=True, capture_output=True, text=True)
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertTrue(all(name.startswith("aicheck-inspection/") for name in names))
                self.assertEqual(len(names), 8)
                self.assertFalse(any(".env" in name or "__pycache__" in name or "/tests/" in name for name in names))
                self.assertEqual(archive.read("aicheck-inspection/references/business-nodes-v3.md"),
                                 (ROOT / "docs/业务节点描述v3.md").read_bytes())
                archive.extractall(folder)
            extracted = Path(folder) / "aicheck-inspection"
            # This interpreter starts outside the repo and has no backend dependencies or config.
            completed = subprocess.run([sys.executable, str(extracted / "scripts/aicheck_client.py"), "rules", "--json", "{}"],
                cwd=folder, env={"PATH": str(Path(sys.executable).parent)}, check=True, capture_output=True, text=True)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual([row["nodeId"] for row in payload["data"]["nodes"]], [4, 5, 6, 7, 8, 9, 12, 13, 16, 24, 25, 26])

    def test_bundled_scripts_only_import_standard_library_or_bundled_client(self):
        allowed = set(sys.stdlib_module_names) | {"aicheck_client", "__future__"}
        for script in (SKILL / "scripts").glob("*.py"):
            tree = ast.parse(script.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                           else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                for module in modules:
                    self.assertIn(module.split(".")[0], allowed, str(script))

    def test_referenced_local_documents_exist(self):
        for document in [SKILL / "SKILL.md", *(SKILL / "references").glob("*.md")]:
            for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
                if "://" not in target and not target.startswith("#"):
                    self.assertTrue((document.parent / target.split("#")[0]).is_file(), target)


if __name__ == "__main__":
    unittest.main()
