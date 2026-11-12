"""节点资料包的依据匹配知识文件：改成先查表后，结果要和原先逐个线性查找完全一致（2026-11-12）。"""
from __future__ import annotations

from pathlib import Path

from apps.api import routes


def _reference_implementation(reference, state):
    def is_rule(file):
        source = next((s for s in state["knowledge_sources"] if s.get("id") == file.get("sourceId")), None)
        return (source or {}).get("sourceType") == "rule" or file.get("sourceType") == "rule"

    raw_path = str(reference.get("file") or reference.get("sourceRelativePath") or "").strip()
    raw_name = str(reference.get("fileName") or "").strip()
    normalized_path = raw_path.replace("\\", "/").lstrip("./")
    file_name = Path(normalized_path).name if normalized_path else raw_name
    standard = [item for item in state["knowledge_files"] if not is_rule(item)]
    if normalized_path:
        exact = next((i for i in standard if str(i.get("sourceRelativePath") or "").replace("\\", "/").lstrip("./") == normalized_path), None)
        if exact:
            return exact
    if not file_name:
        return None
    matches = [i for i in standard if file_name in {str(i.get("fileName") or "").strip(), str(i.get("originalFileName") or "").strip(), Path(str(i.get("sourceRelativePath") or "")).name}]
    return matches[0] if len(matches) == 1 else None


def test_依据匹配知识文件与原逻辑一致(monkeypatch):
    state = {
        "knowledge_sources": [
            {"id": "S-STD", "sourceType": "standard"},
            {"id": "S-RULE", "sourceType": "rule"},
            {"id": "S-RULE", "sourceType": "standard"},  # 重复 id：和 find_one 一样取第一条
        ],
        "knowledge_files": [
            {"id": "K1", "sourceId": "S-STD", "fileName": "GB50184.pdf", "sourceRelativePath": "std/GB50184.pdf"},
            {"id": "K2", "sourceId": "S-RULE", "fileName": "GB50235.pdf", "sourceRelativePath": "rule/GB50235.pdf"},
            {"id": "K3", "sourceId": "S-STD", "sourceType": "rule", "fileName": "TSG.pdf"},
            {"id": "K4", "sourceId": "S-STD", "fileName": "dup.pdf"},
            {"id": "K5", "sourceId": "S-STD", "originalFileName": "dup.pdf"},
            {"id": "K6", "sourceId": None, "fileName": "loose.pdf"},
        ],
    }
    monkeypatch.setattr(routes.repo, "state", {**routes.repo.state, **state})
    references = [
        {"file": "./std/GB50184.pdf"},
        {"file": "rule/GB50235.pdf"},
        {"fileName": "GB50235.pdf"},
        {"fileName": "TSG.pdf"},
        {"fileName": "dup.pdf"},
        {"fileName": "loose.pdf"},
        {"fileName": "missing.pdf"},
        {},
    ]
    for reference in references:
        assert routes.knowledge_file_for_standard_reference(reference) == _reference_implementation(reference, state), reference
