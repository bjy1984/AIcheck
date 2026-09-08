from __future__ import annotations

import json

import pytest

from scripts import ruff_baseline


@pytest.mark.parametrize('update', [False, True])
def test_new_findings_cannot_expand_baseline(monkeypatch, tmp_path, update):
    baseline = tmp_path / 'baseline.json'
    original = json.dumps({'libs/old.py': {'F401': 2}})
    baseline.write_text(original)
    monkeypatch.setattr(ruff_baseline, 'BASELINE_PATH', baseline)
    monkeypatch.setattr(ruff_baseline, 'current_findings', lambda: {'libs/new.py': {'F401': 1}})
    monkeypatch.setattr('sys.argv', ['ruff_baseline', *(['--update'] if update else [])])
    assert ruff_baseline.main() == 1
    assert baseline.read_text() == original


def test_update_only_shrinks_existing_counts(monkeypatch, tmp_path):
    baseline = tmp_path / 'baseline.json'
    baseline.write_text(json.dumps({'libs/a.py': {'F401': 2, 'B023': 1}}))
    monkeypatch.setattr(ruff_baseline, 'BASELINE_PATH', baseline)
    monkeypatch.setattr(ruff_baseline, 'current_findings', lambda: {'libs/a.py': {'F401': 1}})
    monkeypatch.setattr('sys.argv', ['ruff_baseline', '--update'])
    assert ruff_baseline.main() == 0
    assert json.loads(baseline.read_text()) == {'libs/a.py': {'F401': 1}}


def test_line_movement_does_not_change_findings(monkeypatch):
    from types import SimpleNamespace

    def result(row):
        return SimpleNamespace(returncode=0, stdout=json.dumps([
            {'filename': str(ruff_baseline.BACKEND_ROOT / 'libs/a.py'), 'code': 'F401',
             'location': {'row': row, 'column': 1}}
        ]))

    monkeypatch.setattr(ruff_baseline.subprocess, 'run', lambda *a, **k: result(1))
    first = ruff_baseline.current_findings()
    monkeypatch.setattr(ruff_baseline.subprocess, 'run', lambda *a, **k: result(100))
    assert ruff_baseline.current_findings() == first


def test_ruff_failure_with_partial_output_is_not_success(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(ruff_baseline.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=2, stdout='[]', stderr='bad configuration'))
    with pytest.raises(SystemExit):
        ruff_baseline.current_findings()
