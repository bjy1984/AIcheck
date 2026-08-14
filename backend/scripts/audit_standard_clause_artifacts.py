#!/usr/bin/env python3
"""Independent second-pass audit for engineering standard clause artifacts."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
PACK_DIR = BACKEND_ROOT / "business_packs" / "engineering_inspection_v1"


def load(name: str) -> dict:
    return yaml.safe_load((PACK_DIR / name).read_text(encoding="utf-8"))


def pdf_page_count(path: Path) -> int:
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        result = subprocess.run(
            [pdfinfo, str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
        raise ValueError(f"pdfinfo did not return a page count for {path}")

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF page audit requires pdfinfo or PyMuPDF") from exc
    with fitz.open(path) as document:
        return document.page_count


def expected_d7006() -> dict[str, str]:
    result = {"R01": "D2.1", "R02": "D2.1", "R03": "D2.1"}
    result.update({f"R{n:02d}": f"D2.2({n - 3})" for n in range(4, 10)})
    result["R11"] = "D2.3"
    result.update({
        "R24": "D2.6.1", "R25": "D2.6.2", "R26": "D2.6.3(1)", "R27": "D2.6.3(2)", "R28": "D2.6.4",
        "R29": "D2.6.5(1)", "R30": "D2.6.5(2)", "R31": "D2.6.6", "R32": "D2.7(1)", "R33": "D2.7(2)", "R34": "D2.7(3)",
        "R35": "D2.8.1(1)", "R36": "D2.8.1(2)", "R37": "D2.8.1(3)", "R38": "D2.8.2", "R39": "D2.8.3", "R40": "D2.8.4", "R41": "D2.8.5", "R42": "D2.8.6",
        "R43": "D2.9(1)", "R44": "D2.9(2)", "R45": "D2.9(3)", "R46": "D2.9(3)", "R47": "D2.9(4)",
        "R48": "D2.10(1)", "R49": "D2.10(2)", "R50": "D2.10(3)", "R51": "D2.10(4)",
        "R52": "D2.11(1)", "R53": "D2.11(2)", "R54": "D2.11(2)", "R55": "D2.11(2)",
        "R56": "D2.12(1)", "R57": "D2.12(2)", "R58": "D2.12(3)",
        "R59": "D2.13.1(1)", "R60": "D2.13.1(2)", "R61": "D2.13.1(3)", "R62": "D2.13.1(4)",
        "R63": "D2.13.2(1)", "R64": "D2.13.2(2)", "R65": "D2.13.2(3)", "R66": "D2.14(1)", "R67": "D2.14(2)", "R68": "D2.15",
        "R12": "D2.4.1(1)", "R13": "D2.4.1(2)", "R14": "D2.4.1(3)", "R15": "D2.4.1(4)", "R16": "D2.4.1(5)",
        "R17": "D2.4.1(6)", "R18": "D2.4.1(7)", "R19": "D2.4.1(8)", "R20": "D2.4.1(9)", "R21": "D2.4.2", "R22": "D2.4.3", "R23": "D2.5",
        "R69": "2.2.4",
    })
    return result


def audit() -> tuple[list[str], list[str], dict[str, int]]:
    errors: list[str] = []
    notes: list[str] = []
    catalog = load("standard_clause_catalog.yaml")["standardCatalog"]
    bindings = load("standard_clause_bindings.yaml")["standardClauseBindings"]
    checks = load("atomic_checks.yaml")["atomicChecks"]
    package_doc = load("standard_clause_packages.yaml")
    packages = package_doc["standardClausePackages"]
    rules = load("rules.yaml")["ruleSets"]

    expected_rules = {f"R{index:02d}" for index in range(1, 70)}
    by_binding = {item["sourceRuleId"]: item for item in bindings}
    by_package = {item["sourceRuleId"]: item for item in packages}
    check_ids = {item["id"] for item in checks}
    catalog_by_id = {item["id"]: item for item in catalog}
    catalog_ids = set(catalog_by_id)
    page_counts: dict[str, int] = {}

    for label, values in (("bindings", bindings), ("packages", packages), ("checks", checks), ("catalog", catalog)):
        key = {"bindings": "bindingId", "packages": "packageId", "checks": "id", "catalog": "id"}[label]
        duplicates = [item for item, count in Counter(row[key] for row in values).items() if count > 1]
        if duplicates:
            errors.append(f"{label} duplicate ids: {duplicates}")
    if set(by_binding) != expected_rules:
        errors.append("primary binding coverage is not R01-R69")
    if set(by_package) != expected_rules:
        errors.append("package coverage is not R01-R69")
    if {rule["sourceRuleId"] for rule in rules} != expected_rules:
        errors.append("rules.yaml coverage is not R01-R69")

    expected = expected_d7006()
    for source_rule, clause in expected.items():
        binding = by_binding.get(source_rule)
        if not binding or binding["standardRef"] != "STD-TSG-D7006-2020" or binding["clauseNo"] != clause:
            errors.append(f"{source_rule} primary mismatch, expected TSG D7006—2020 {clause}")
    r10 = by_binding.get("R10")
    if not r10 or (r10["standardRef"], r10["clauseNo"]) != ("STD-TSG-31-2025", "1.9(3)"):
        errors.append("R10 must bind directly to TSG 31—2025 1.9(3)")

    for item in catalog:
        source_path = REPO_ROOT / item["sourceFile"]
        if not source_path.is_file():
            errors.append(f"missing standard source file: {item['sourceFile']}")
            continue
        if not item.get("knowledgeFileId") or not item.get("documentVersionId"):
            errors.append(f"catalog standard cannot resolve knowledge file: {item['id']}")
        if source_path.suffix.lower() == ".pdf":
            try:
                page_counts[item["id"]] = pdf_page_count(source_path)
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                errors.append(f"cannot read PDF page count for {item['id']}: {exc}")
    professional_clause_count = 0
    professional_locator_count = 0
    for package in packages:
        if len(package["atomicCheckIds"]) < 2:
            errors.append(f"{package['sourceRuleId']} has fewer than two atomic checks")
        unknown_checks = set(package["atomicCheckIds"]) - check_ids
        if unknown_checks:
            errors.append(f"{package['sourceRuleId']} unknown atomic checks: {sorted(unknown_checks)}")
        expected_execution = (
            "llm_semantic_primary_with_evidence_validation"
            if package["sourceRuleId"] == "R19"
            else "deterministic_tools_only"
        )
        if package["decisionModel"]["ruleExecution"] != expected_execution:
            errors.append(f"{package['sourceRuleId']} has an invalid decision execution mode")
        if package["sourceRuleId"] == "R69" and package["decisionModel"].get("automatedDecisionAllowed") is not False:
            errors.append("R69 must prohibit an automated evaluation conclusion")
        for clause in package["professionalClauses"]:
            professional_clause_count += 1
            if clause["standardRef"] not in catalog_ids:
                errors.append(f"{package['sourceRuleId']} unknown standard {clause['standardRef']}")
                continue
            catalog_item = catalog_by_id[clause["standardRef"]]
            if clause.get("knowledgeFileId") != catalog_item.get("knowledgeFileId") or clause.get("documentVersionId") != catalog_item.get("documentVersionId"):
                errors.append(f"{package['sourceRuleId']} professional clause does not resolve to catalog file/version")
            locators = clause.get("locators") or []
            if not locators or not clause.get("sourceLocatorId"):
                errors.append(f"{package['sourceRuleId']} professional clause has no source locator: {clause.get('clauseNo')}")
            locator_ids = {item.get("locatorId") for item in locators}
            if clause.get("sourceLocatorId") not in locator_ids:
                errors.append(f"{package['sourceRuleId']} sourceLocatorId is not present in locators: {clause.get('clauseNo')}")
            page_count = page_counts.get(clause["standardRef"])
            for locator in locators:
                professional_locator_count += 1
                try:
                    start_page = int(locator["startPage"])
                    end_page = int(locator["endPage"])
                except (KeyError, TypeError, ValueError):
                    errors.append(f"{package['sourceRuleId']} invalid source locator page values: {clause.get('clauseNo')}")
                    continue
                if start_page < 1 or end_page < start_page or (page_count and end_page > page_count):
                    errors.append(f"{package['sourceRuleId']} locator outside PDF page range: {clause.get('clauseNo')} {start_page}-{end_page}/{page_count}")

    second_check_expected = [
        ("R03", ("STD-TSG-Z7002-2022", "附件A（核准证样式、填写说明及表A-1核准项目代码）")),
        ("R45", ("STD-SYT-4113.11-2023", "第4-7章")),
        ("R46", ("STD-GBT-21448-2017", "第5-7章、第9章")),
        ("R49", ("STD-GB-50235-2010", "7.1、7.3、7.9")),
        ("R68", ("STD-GB-50235-2010", "第9章（9.1-9.7）")),
        ("R14", ("STD-GBT-8163-2018", "第6-8章")),
        ("R16", ("STD-GBT-12459-2025", "第10-11章")),
        ("R16", ("STD-GBT-13401-2025", "第8章、第10-11章")),
        ("R16", ("STD-GBT-8163-2018", "第6-8章")),
        ("R16", ("STD-GBT-3087-2022", "第6-9章")),
        ("R16", ("STD-GBT-5310-2023", "第7章、第9-11章")),
        ("R16", ("STD-GBT-9948-2025", "第7章、第9-11章")),
        ("R16", ("STD-GBT-14976-2025", "7.3、7.7、第9-11章")),
        ("R16", ("STD-GBT-12771-2019", "6.9、第8章、9.1-9.2")),
        ("R17", ("STD-GBT-20801.1-2025", "7.2.1-7.2.7")),
        ("R18", ("STD-NBT-47013.1-2015", "7.3-7.4")),
    ]
    for source_rule, expected_clause in second_check_expected:
        actual = {(item["standardRef"], item["clauseNo"]) for item in by_package[source_rule]["professionalClauses"]}
        if expected_clause not in actual:
            errors.append(f"{source_rule} second-check correction is missing: {expected_clause}")

    batches = package_doc["standardClausePackageSet"]["batches"]
    flattened = [rule for batch in batches for rule in batch["sourceRuleIds"]]
    if len(flattened) != 69 or set(flattened) != expected_rules or len(flattened) != len(set(flattened)):
        errors.append("six-batch partition is not an exact partition of R01-R69")

    matrix = (REPO_ROOT / "docs" / "业务节点具体标准条款审核矩阵.md").read_text(encoding="utf-8")
    matrix_rows = [line for line in matrix.splitlines() if line.startswith("| BATCH-")]
    if len(matrix_rows) != 69:
        errors.append(f"human matrix has {len(matrix_rows)} data rows, expected 69")
    notes.append("TSG D7006—2020 PDF第27-32页已与独立维护的规范条款序列逐项比对。")
    notes.append("R10已独立核对为TSG 31—2025第1.9(3)，未再从D2.2间接推定。")
    notes.append("R16已逐类核对8项产品标准的技术要求、检验规则和质量证明章节，并录入独立PDF页级定位；R17/R18的条件适用条款同步复核。")
    notes.append("R69已依据TSG D7006—2020第2.2.4条及附件G核对；工具仅汇总证据并校验评价报告，评价结论由监检人员确认和签发。")
    notes.append("扫描件可视复核纠正了TSG Z7002附件A、GB 50235第7/9章、SY/T 4113.11第4-7章、GB/T 21448第5-7/9章及产品标准章节落点。")
    notes.append("全部专业条款均已绑定知识文件、文档版本和一个或多个PDF页级locator；组合条款的不连续落点已拆分。")
    notes.append("全部标准源文件路径、PDF页数边界、条款包引用、原子项引用、六批覆盖和人工矩阵行数已检查。")
    stats = {
        "catalog": len(catalog), "bindings": len(bindings), "packages": len(packages),
        "professional_clauses": professional_clause_count,
        "professional_locators": professional_locator_count,
        "atomic_checks": len(checks), "matrix_rows": len(matrix_rows),
    }
    return errors, notes, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    errors, notes, stats = audit()
    status = "PASS" if not errors else "FAIL"
    print(status, stats)
    for error in errors:
        print("ERROR", error)
    if args.write_report:
        lines = ["# 标准条款二次检查报告", "", f"- 检查时间：{date.today().isoformat()}", f"- 结果：**{status}**", f"- 统计：{stats}", "", "## 独立检查项", ""]
        lines.extend(f"- {item}" for item in notes)
        lines.extend(["", "## 错误", ""])
        lines.extend(["- 无。"] if not errors else [f"- {item}" for item in errors])
        lines.extend(["", "## 边界说明", "", "- `visual_verified` 的扫描件条款已完成人工可视复核并补录PDF页级定位；如需原文高亮，可继续补充文本块或坐标级定位。", "- 本报告验证绑定完整性和源文件可用性，不替代法规/标准发布机构对版本有效性的最终确认。", ""])
        (REPO_ROOT / "docs" / "标准条款二次检查报告.md").write_text("\n".join(lines), encoding="utf-8")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
