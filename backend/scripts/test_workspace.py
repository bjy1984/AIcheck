"""Build and prune the exact source manifest for an isolated test workspace."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

MARKER = '.aicheck-test-workspace'
MANIFEST = '.aicheck-test-manifest.json'
EXCLUDED = ('rules/results/', 'rules/standards/', 'audit-reports/', 'Scan/',
            'backend/data/visual_extraction_pages/', 'output/', 'tmp/')
GENERATED = ('output', 'tmp', 'backend/data/runtime-exports', 'backend/ocr_eval/reports',
             'backend/data/aicheck.sqlite3')


def source_files(root: Path) -> list[str]:
    names = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root
    ).decode().split('\0')
    result = []
    for name in sorted(set(names)):
        if not name or name.startswith(EXCLUDED) or name.endswith(('.zip', '.dump', '.mp4')):
            continue
        path = root / name
        if not path.is_file():
            continue
        if path.is_symlink() or '\n' in name or '\r' in name:
            raise ValueError(f'Unsupported test source path: {name}')
        # Runtime credentials never belong in a test archive.
        if path.name == '.env' or path.name.endswith('-secrets.env'):
            raise ValueError(f'Refusing runtime environment file: {name}')
        result.append(name)
    return result


def safe_path(root: Path, name: str) -> Path:
    path = root / name
    if not name or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError(f'Unsafe manifest path: {name}')
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Test workspace path escapes root: {name}')
    return path


def prepare(root: Path, names: list[str]) -> None:
    if root.is_symlink() or root.parent != Path('/tmp') or not root.name.startswith('aicheck-tests-'):
        raise ValueError('Workspace must be /tmp/aicheck-tests-<name>, without symlinks')
    root.mkdir(exist_ok=True)
    marker = root / MARKER
    if not marker.exists() and any(root.iterdir()):
        raise ValueError('Refusing to adopt a nonempty, unmarked workspace')
    marker.write_text('isolated-tests-v1\n')
    old_manifest = root / MANIFEST
    old = json.loads(old_manifest.read_text()) if old_manifest.exists() else []
    # Validate the entire plan before deleting anything.
    for name in [*names, *old, *GENERATED]:
        safe_path(root, name)
    for name in set(old) - set(names):
        safe_path(root, name).unlink(missing_ok=True)
    for name in GENERATED:
        path = safe_path(root, name)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    old_manifest.write_text(json.dumps(names, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['manifest', 'prepare'])
    parser.add_argument('root', type=Path)
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    if args.mode == 'manifest':
        print('\n'.join(source_files(args.root)))
    else:
        prepare(args.root, args.manifest.read_text().splitlines())


if __name__ == '__main__':
    main()
