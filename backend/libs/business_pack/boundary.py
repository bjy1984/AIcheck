from __future__ import annotations

from pathlib import Path

DEFAULT_FORBIDDEN_TERMS = (
    "施工方",
    "监检员",
    "无损检测",
    "建设方",
    "焊口",
    "底片",
    "压力管道",
)

DEFAULT_CORE_PATHS = (
    "backend/libs/business_pack/__init__.py",
    "backend/libs/business_pack/loader.py",
)


def scan_core_boundary(
    *,
    root: Path | None = None,
    paths: tuple[str, ...] = DEFAULT_CORE_PATHS,
    forbidden_terms: tuple[str, ...] = DEFAULT_FORBIDDEN_TERMS,
) -> list[dict[str, object]]:
    base = root or Path(__file__).resolve().parents[3]
    violations: list[dict[str, object]] = []
    for relative_path in paths:
        target = base / relative_path
        if not target.exists():
            continue
        files = [target] if target.is_file() else sorted(target.rglob("*.py"))
        for path in files:
            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                for term in forbidden_terms:
                    if term in line:
                        violations.append(
                            {
                                "file": str(path.relative_to(base)),
                                "line": line_no,
                                "term": term,
                            }
                        )
    return violations
