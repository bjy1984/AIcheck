from __future__ import annotations

import json
import os

import pytest

from scripts.compare_jev_primary_live import _append_private, _reserved_nodes


def test_private_journal_reserves_once_before_result(tmp_path):
    path = tmp_path / "runs.jsonl"
    _append_private(path, {"event": "reserved", "nodeId": 13})
    _append_private(path, {"event": "result", "nodeId": 13, "report": {"status": "completed"}})
    assert _reserved_nodes(path) == {13}
    assert [json.loads(line)["event"] for line in path.read_text().splitlines()] == ["reserved", "result"]
    assert os.stat(path).st_mode & 0o077 == 0


def test_public_journal_is_rejected(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text("{}\n")
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private_journal_permissions_required"):
        _reserved_nodes(path)
    with pytest.raises(ValueError, match="private_journal_permissions_required"):
        _append_private(path, {"event": "reserved", "nodeId": 13})
