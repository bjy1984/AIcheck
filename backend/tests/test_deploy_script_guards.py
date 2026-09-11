"""部署脚本的几道假成功，用文本守卫钉住。

2026-09-10：服务器树有一份手改，git checkout 失败，内层 sh 没 set -e，后续命令
把退出码盖成 0；镜像用旧树建、标签却按本机 REVISION 变量盖章，最后的版本校验
拿同一个变量去比——全程报「部署完成」，线上跑的是旧代码。
"""
from __future__ import annotations

import pathlib
import re

SCRIPT = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "deploy_to_server.sh").read_text(encoding="utf-8")


def _checkout_block() -> str:
    start = SCRIPT.index("git checkout --quiet --detach")
    return SCRIPT[SCRIPT.rfind("$GIT_IMAGE -c '", 0, start):start + 600]


def test_内层shell开了set_e():
    assert "set -e" in _checkout_block(), "内层 sh 不开 set -e，checkout 失败会被后面的命令盖成成功"


def test_检出前拒绝带手改的树():
    block = _checkout_block()
    assert "git status --porcelain" in block and "拒绝部署" in block


def test_检出后断言HEAD等于目标():
    block = _checkout_block()
    assert "git rev-parse HEAD" in block and "不是目标" in block


def test_镜像标签来自服务器树而不是本机变量():
    build = re.search(r"docker build[^\n]*Dockerfile.server[^\n]*", SCRIPT).group(0)
    assert "AICHECK_REVISION=$REVISION" not in build, "同源比对不是校验：标签得从实际检出的树取"
    assert "BUILT_REV" in build


def test_版本校验仍然执行():
    assert "verify_runtime_revision.py --expected-revision" in SCRIPT
