import yaml

from scripts import generate_atomic_check_tool_plan as generator


def test_all_bindings_regenerate_without_changing_audited_contract(tmp_path, monkeypatch):
    committed = yaml.safe_load(generator.BINDINGS.read_text())
    monkeypatch.setattr(generator, "BINDINGS", tmp_path / "bindings.yaml")
    monkeypatch.setattr(generator, "DOCUMENT", tmp_path / "tools.md")
    generator.main()
    generated = yaml.safe_load(generator.BINDINGS.read_text())
    assert generated == committed
    first = generator.BINDINGS.read_bytes()
    generator.main()
    assert generator.BINDINGS.read_bytes() == first
    assert generator.DOCUMENT.is_file()


def test_r35_regeneration_preserves_decision_role_without_publishing():
    checks = yaml.safe_load(generator.SOURCE.read_text())["atomicChecks"]
    rows = [generator.make_binding(row) for row in checks if row["sourceRuleId"] == "R35"]
    assert all(row["implementationStatus"] == "binding_only" for row in rows)
    assert "R35" not in generator.PILOT_RULES
    assert rows[0]["parameters"]["decisionTool"] == "evaluate_ndt_quality_system"
    assert rows[1]["parameters"]["resultRole"] == "evidence_gate"
    assert "check_date_covers" not in rows[0]["tools"]
    assert "check_required" not in rows[0]["tools"]
    rows[0]["parameters"]["decisionTool"] = "tampered"
    assert generator.make_binding(next(row for row in checks if row["id"] == "AC-R35-01"))["parameters"]["decisionTool"] == "evaluate_ndt_quality_system"


def test_standalone_generator_works_from_unrelated_directory(tmp_path):
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    script_dir = tmp_path / "backend" / "scripts"
    pack_dir = tmp_path / "backend" / "business_packs" / "engineering_inspection_v1"
    script_dir.mkdir(parents=True)
    pack_dir.mkdir(parents=True)
    for name in ("generate_atomic_check_tool_plan.py", "atomic_binding_overrides.py"):
        shutil.copy(Path(generator.__file__).with_name(name), script_dir / name)
    shutil.copy(generator.SOURCE, pack_dir / "atomic_checks.yaml")
    completed = subprocess.run([sys.executable, str(script_dir / "generate_atomic_check_tool_plan.py")],
                               cwd=tmp_path, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert yaml.safe_load((pack_dir / "atomic_check_tool_bindings.yaml").read_text()) == yaml.safe_load(generator.BINDINGS.read_text())
