from __future__ import annotations

import pytest

from libs.material_targeting import load_review_points_from_mapping_doc

HEADER = '|节点|上传资料类型|审查内容|\n|---|---|---|\n'
ROWS = ['|1|设计许可 `license`|许可范围|', '|2|施工图 `drawing`|图纸审查|']


def ids(path, rows):
    path.write_text(HEADER + '\n'.join(rows))
    return {item['reviewContent']: item['id'] for item in load_review_points_from_mapping_doc(path)}


def test_insert_reorder_and_remove_unrelated_rows_preserve_ids(tmp_path):
    path = tmp_path / 'mapping.md'
    initial = ids(path, ROWS)
    inserted = ids(path, [ROWS[0], '|3|其他 `other`|新增审查|', ROWS[1]])
    assert all(inserted[key] == value for key, value in initial.items())
    assert ids(path, list(reversed(ROWS))) == initial
    assert ids(path, ROWS[1:])['图纸审查'] == initial['图纸审查']


def test_content_change_only_changes_its_own_id(tmp_path):
    path = tmp_path / 'mapping.md'
    initial = ids(path, ROWS)
    changed = ids(path, [ROWS[0].replace('许可范围', '有效期限'), ROWS[1]])
    assert changed['图纸审查'] == initial['图纸审查']
    assert changed['有效期限'] != initial['许可范围']


def test_duplicate_business_identity_and_hash_collision_are_rejected(tmp_path, monkeypatch):
    path = tmp_path / 'mapping.md'
    with pytest.raises(ValueError, match='Duplicate'):
        ids(path, [ROWS[0], ROWS[0]])
    monkeypatch.setattr('libs.material_targeting.stable_short_id', lambda *a, **k: 'COLLIDE')
    with pytest.raises(ValueError, match='Duplicate'):
        ids(path, [ROWS[0], ROWS[0].replace('许可范围', '有效期限')])
