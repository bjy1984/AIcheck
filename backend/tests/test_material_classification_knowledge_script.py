from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts" / "validate_material_classification_knowledge.py"
KNOWLEDGE = BACKEND_ROOT / "config" / "material_classification_knowledge.json"


def run_validator(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--knowledge", str(path)],
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_accepts_the_complete_60_card_knowledge_file():
    result = run_validator(KNOWLEDGE)

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["ok"] is True
    assert output["cardCount"] == 60
    assert output["standardSupportedCount"] > 0
    assert output["standardSupportedCount"] + output["businessDefinedCount"] == 60
    assert output["errors"] == []


def test_cli_rejects_a_card_without_required_signals(tmp_path: Path):
    payload = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    payload["cards"][0]["requiredSignals"] = []
    invalid = tmp_path / "invalid-knowledge.json"
    invalid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = run_validator(invalid)

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["ok"] is False
    assert "REQUIRED_LIST_EMPTY" in {item["code"] for item in output["errors"]}
