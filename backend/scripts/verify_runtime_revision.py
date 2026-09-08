"""Verify API and workers run the same image built from the requested commit."""
from __future__ import annotations

import argparse
import subprocess

SERVICES = ('aicheck-api', 'aicheck-worker-business', 'aicheck-worker-cpu-heavy',
            'aicheck-worker-llm', 'aicheck-worker-ocr-remote')


def verify(expected_revision: str) -> None:
    output = subprocess.check_output([
        'docker', 'inspect', '--format',
        '{{.Name}} {{.Image}} {{.State.Running}} {{index .Config.Labels "org.opencontainers.image.revision"}}',
        *SERVICES,
    ], text=True)
    rows = [line.split() for line in output.splitlines()]
    if len(rows) != len(SERVICES) or any(len(row) != 4 for row in rows):
        raise ValueError('Incomplete runtime revision response')
    if {row[0].lstrip('/') for row in rows} != set(SERVICES):
        raise ValueError('Missing API or worker service')
    if len({row[1] for row in rows}) != 1:
        raise ValueError('API and worker images differ')
    for name, _, running, revision in rows:
        if running != 'true' or revision != expected_revision:
            raise ValueError(f'{name}: stopped or wrong deployment revision')
    print(f'API and all workers verified at {expected_revision}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-revision', required=True)
    verify(parser.parse_args().expected_revision)


if __name__ == '__main__':
    main()
