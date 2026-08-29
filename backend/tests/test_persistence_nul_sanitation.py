"""NUL sanitation in canonical persistence payload.

PostgreSQL jsonb rejects NUL (UntranslatableCharacter) and the whole write fails.
NUL enters payloads via OCR text and external file names; we cannot intercept every
entry point, so the last line of defence is at serialization: dropping one invisible
character beats losing the whole record.

The same function feeds baseline comparison, so both sides must use the sanitized
form — otherwise every record looks "changed" and gets rewritten forever.
"""

from __future__ import annotations

import json


def test_nul_is_stripped_from_serialized_payload() -> None:
    from libs.db.repository import InMemoryRepository

    payload = {"text": "before" + chr(0) + "after", "nested": [{"v": chr(0)}]}
    serialized = InMemoryRepository.canonical_persistence_payload(payload)

    assert chr(92) + "u0000" not in serialized
    assert chr(0) not in serialized
    # 内容其余部分保持不变，只掉那个不可见字符
    assert json.loads(serialized)["text"] == "beforeafter"
    assert json.loads(serialized)["nested"][0]["v"] == ""


def test_clean_payload_is_untouched() -> None:
    from libs.db.repository import InMemoryRepository

    payload = {"b": 2, "a": "\u00e4\u00f6 chinese \u4e2d\u6587"}
    serialized = InMemoryRepository.canonical_persistence_payload(payload)
    assert json.loads(serialized) == payload
    # 仍然是排序键的规范形式（基线比对依赖它）
    assert serialized.index('"a"') < serialized.index('"b"')
