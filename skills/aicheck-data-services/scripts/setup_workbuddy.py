#!/usr/bin/env python3
"""Generate a private, portable MCP configuration; never edit platform settings."""
from __future__ import annotations
import argparse
import getpass
import ipaddress
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from urllib.parse import urlsplit

NAME = 'aicheck-data-services'
DEFAULT_CONFIG = Path.home() / '.aicheck' / 'workbuddy' / 'mcp.json'


def base_url(value):
    value = value.strip().rstrip('/')
    try:
        u = urlsplit(value)
        _ = u.port
        local = u.hostname == 'localhost'
        try:
            local = local or ipaddress.ip_address(u.hostname or '').is_loopback
        except ValueError:
            pass
        if (not u.hostname or u.username or u.password or u.query or u.fragment
                or (u.scheme != 'https' and not (u.scheme == 'http' and local))):
            raise ValueError()
    except ValueError:
        raise ValueError('服务地址须为 HTTPS；仅本机联调允许 HTTP。不要包含用户名、密码、查询参数。') from None
    return value


def existing_path(value, directory=False):
    p = Path(value).expanduser().resolve()
    if not (p.is_dir() if directory else p.is_file()):
        raise ValueError('资料目录或令牌文件不存在，请检查路径。')
    return p


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids silently overwriting tokens or following a symlink.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)


def generate(url, roots, token_file, output, token=None):
    url = base_url(url)
    roots = list(dict.fromkeys(str(existing_path(r, True)) for r in roots))
    if not roots:
        raise ValueError('至少指定一个允许上传的资料目录。')
    output = Path(output).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('配置文件已存在。请换一个输出文件名；已有平台配置不会被覆盖。')
    token_file = Path(token_file).expanduser().absolute()
    if output == token_file:
        raise ValueError('配置文件与令牌文件不能使用同一路径。')
    if token is None:
        token_file = existing_path(token_file)
        token = token_file.read_text(encoding='utf-8').strip()
        new_token = False
    else:
        token = token.strip().removeprefix('Bearer ').strip()
        new_token = True
    if not token or '\n' in token or '\r' in token:
        raise ValueError('令牌必须是非空单行文本。')
    config = {'mcpServers': {NAME: {
        'type': 'stdio', 'command': sys.executable,
        'args': [str(Path(__file__).resolve().with_name('mcp_server.py'))],
        'env': {'AICHECK_BASE_URL': url, 'AICHECK_TOKEN_FILE': str(token_file),
                'AICHECK_DATA_ALLOWED_ROOTS': json.dumps(roots, ensure_ascii=False),
                'AICHECK_TIMEOUT': '300'}, 'disabled': False,
    }}}
    if new_token:
        private_write(token_file, token + '\n')
    private_write(output, json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    return output


def check(config_path):
    config = json.loads(Path(config_path).expanduser().read_text(encoding='utf-8'))
    server = config['mcpServers'][NAME]
    env = os.environ.copy()
    # Use the selected token file, not a stale credential inherited from a shell.
    env.pop('AICHECK_TOKEN', None)
    env.update(server['env'])
    env['AICHECK_TIMEOUT'] = '20'
    messages = [
        {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'aicheck-setup','version':'1.1.0'}}},
        {'jsonrpc':'2.0','method':'notifications/initialized'},
        {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}},
        {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'aicheck_connection','arguments':{}}},
    ]
    try:
        proc = subprocess.run([server['command'], *server['args']],
            input=''.join(json.dumps(m)+'\n' for m in messages),
            capture_output=True, text=True, encoding='utf-8', env=env, timeout=35)
        responses = {r['id']: r for r in map(json.loads, proc.stdout.splitlines())}
        tools = responses[2]['result']['tools']
        result = json.loads(responses[3]['result']['content'][0]['text'])
        if proc.returncode or 'result' not in responses[1] or len(tools) != 9:
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        print('自检失败：MCP 启动或协议异常。检查 Python、脚本路径及网络；未显示进程输出以避免泄露凭据。')
        return 1
    print('本地 MCP 握手成功；发现 9 个工具。')
    if not result.get('ok'):
        print('后台连接失败，错误码：' + str(result.get('error', {}).get('code', 'unknown')))
        return 1
    print('后台 connection 调用成功。此项不验证 OCR 令牌、任务执行或官方证件查询。')
    print('仍需在 WorkBuddy 启用并信任此 MCP，然后使用指定 PDF 完成 OCR 验收。')
    return 0


def main():
    parser = argparse.ArgumentParser(description='AIcheck WorkBuddy 配置向导（Python 3.10+）')
    parser.add_argument('--base-url', help='管理员提供的 HTTPS 服务地址')
    parser.add_argument('--allow-root', action='append', help='允许上传目录，可重复指定')
    parser.add_argument('--token-file', help='已有的个人令牌文件，不把令牌写入命令行')
    parser.add_argument('--output', default=str(DEFAULT_CONFIG), help='生成的配置片段路径，不覆盖已有文件')
    parser.add_argument('--check', metavar='CONFIG', help='只对已生成的可信配置进行连接自检')
    args = parser.parse_args()
    try:
        if args.check:
            return check(args.check)
        url = args.base_url or input('管理员提供的 HTTPS 服务地址：').strip()
        roots = args.allow_root or [input('允许处理的资料目录（文件夹完整路径）：').strip()]
        token_file = args.token_file
        token = None
        if not token_file:
            token_file = str(Path(args.output).expanduser().absolute().with_name('aicheck-token.txt'))
            token = getpass.getpass('个人访问令牌（输入隐藏，请向管理员获取）：')
        path = generate(url, roots, token_file, args.output, token)
        print(f'配置已生成：{path}')
        print('将 mcpServers 内的 aicheck-data-services 条目合并到 WorkBuddy MCP 配置，保留其他条目。')
        print('启用并信任该连接器；解压目录应保持不变。')
        print('自检命令：')
        command = [sys.executable, str(Path(__file__).resolve()), '--check', str(path)]
        print(subprocess.list2cmdline(command) if os.name == 'nt' else shlex.join(command))
        return 0
    except (OSError, ValueError, KeyError, EOFError):
        print('配置失败：请检查服务地址、目录及令牌文件；输出文件已存在时请换文件名。不会覆盖已有文件，也不会打印令牌。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
