"""Verify API and workers run the same image built from the requested commit.

本脚本在**宿主机**执行（它要用宿主机的 docker CLI），而目标机的 python3 是 3.6，
不支持 `from __future__ import annotations`（3.7 才加入）。脚本里的类型注解本身
3.6 就能用，所以不要再把那行加回来——2026-09-10 部署最后一步就是栽在这里，
前面全部成功、只有版本校验报 SyntaxError，退出码 1 让整次部署看起来是失败的。
"""
import argparse
import subprocess

SERVICES = ('aicheck-api', 'aicheck-worker-business', 'aicheck-worker-cpu-heavy',
            'aicheck-worker-llm', 'aicheck-worker-ocr-remote')


def verify(expected_revision: str) -> None:
    output = subprocess.check_output([
        'docker', 'inspect', '--format',
        '{{.Name}} {{.Image}} {{.State.Running}} {{index .Config.Labels "org.opencontainers.image.revision"}}',
        *SERVICES,
    # text= 同样是 3.7 才有的参数；3.6 要用 universal_newlines=，两者语义一致。
    ], universal_newlines=True)
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
