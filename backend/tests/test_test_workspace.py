from __future__ import annotations

import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from scripts.test_workspace import MANIFEST, prepare, source_files


def test_manifest_includes_new_files_and_fixtures_but_not_deleted_or_ignored(tmp_path):
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    (tmp_path / '.gitignore').write_text('.env\n')
    (tmp_path / 'deleted.py').write_text('')
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    (tmp_path / 'deleted.py').unlink()
    (tmp_path / 'new_test.py').write_text('')
    (tmp_path / '.env').write_text('PRIVATE=never-sync')
    (tmp_path / 'test2').mkdir()
    (tmp_path / 'test2/fixture.pdf').write_bytes(b'fixture')
    (tmp_path / 'output/two_project_ai_review_20260825').mkdir(parents=True)
    (tmp_path / 'output/two_project_ai_review_20260825/review_input.json').write_text('{}')
    (tmp_path / 'output/private-output.json').write_text('{}')
    names = source_files(tmp_path)
    assert 'output/two_project_ai_review_20260825/review_input.json' in names
    assert 'output/private-output.json' not in names
    assert 'new_test.py' in names
    assert 'test2/fixture.pdf' in names
    assert 'deleted.py' not in names
    assert '.env' not in names


def test_prune_only_previous_manifest_and_reset_generated_outputs():
    with TemporaryDirectory(prefix='aicheck-tests-', dir='/tmp') as directory:
        root = Path(directory)
        prepare(root, ['old.py'])
        (root / 'old.py').write_text('stale')
        (root / 'unlisted.txt').write_text('keep')
        (root / 'output').mkdir()
        (root / 'output/result').write_text('generated')
        prepare(root, ['new.py'])
        assert not (root / 'old.py').exists()
        assert not (root / 'output').exists()
        assert (root / 'unlisted.txt').read_text() == 'keep'
        assert json.loads((root / MANIFEST).read_text()) == ['new.py']


def test_prepare_refuses_unsafe_and_unmarked_workspaces(tmp_path):
    with pytest.raises(ValueError):
        prepare(tmp_path, [])
    with TemporaryDirectory(prefix='aicheck-tests-', dir='/tmp') as directory:
        root = Path(directory)
        (root / 'keep').write_text('existing')
        with pytest.raises(ValueError):
            prepare(root, [])
        assert (root / 'keep').exists()


def test_invalid_manifest_cannot_delete_previous_files():
    with TemporaryDirectory(prefix='aicheck-tests-', dir='/tmp') as directory:
        root = Path(directory)
        prepare(root, ['keep.py'])
        (root / 'keep.py').write_text('keep')
        with pytest.raises(ValueError):
            prepare(root, ['../outside'])
        assert (root / 'keep.py').exists()
