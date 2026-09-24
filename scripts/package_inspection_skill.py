#!/usr/bin/env python3
"""Build a credential-free, single-root Agent Skill archive from an explicit allowlist."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/aicheck-inspection"
FILES = (
    "SKILL.md", "agents/openai.yaml",
    "references/business-nodes-v3.md", "references/review-contract.md",
    "references/backend-workflow.md", "references/platform-setup.md",
    "scripts/aicheck_client.py", "scripts/mcp_server.py",
)


def build(output):
    canonical = (ROOT / "docs/业务节点描述v3.md").read_bytes()
    if (SKILL / "references/business-nodes-v3.md").read_bytes() != canonical:
        raise ValueError("Bundled business-node reference differs from canonical docs")
    for relative in FILES:
        file = SKILL / relative
        if not file.is_file() or file.is_symlink():
            raise ValueError(f"Missing or unsafe distribution file: {relative}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in FILES:
            archive.write(SKILL / relative, f"aicheck-inspection/{relative}")
    report = {"archive": output.name, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
              "ruleSha256": hashlib.sha256(canonical).hexdigest(), "files": list(FILES)}
    output.with_suffix(".manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/skills/aicheck-inspection.zip")
    build(parser.parse_args().output.resolve())
