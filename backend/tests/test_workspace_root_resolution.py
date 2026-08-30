"""local:// 文件的根目录解析必须靠「哪一层有 output/」，不能靠目录层数倒推。

容器里代码在 /app/apps/worker/tasks.py，parents[3] 是 /，而文件在 /app/output/。
少一层目录，所有 local:// 路径就全部解析失败——2026-08-29 审计中，13 份实际
存在于 /app/output/ 的资料被判成「源文件已丢失」，差点让用户白白重传。

routes.py 早修过同款 bug（当时 66 个线上文件预览失效），worker 漏修。
判据只留一份实现，两处共用。
"""

from __future__ import annotations

import pathlib

from libs.workspace_paths import resolve_workspace_root

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_env_override_wins(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AICHECK_WORKSPACE_ROOT", str(tmp_path))
    assert resolve_workspace_root() == tmp_path.resolve()


def test_picks_the_ancestor_that_actually_has_output(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AICHECK_WORKSPACE_ROOT", raising=False)
    # 模拟容器布局：/app/output 存在，代码在 /app/apps/worker/
    app = tmp_path / "app"
    (app / "output").mkdir(parents=True)
    code = app / "apps" / "worker"
    code.mkdir(parents=True)
    resolved = resolve_workspace_root(code / "tasks.py")
    assert resolved == app, "必须选中真的有 output/ 的那一层，而不是往上数三层"


def test_no_hardcoded_parents_index_in_worker() -> None:
    """worker 不得再用层数倒推。"""
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    assert "WORKSPACE_ROOT = Path(__file__).resolve().parents[3]" not in source
    assert "resolve_workspace_root" in source


def test_single_implementation_shared_by_api_and_worker() -> None:
    api = (BACKEND_ROOT / "apps" / "api" / "routes.py").read_text(encoding="utf-8")
    worker = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    for source in (api, worker):
        assert "from libs.workspace_paths import resolve_workspace_root" in source
    # routes.py 不再保留本地副本
    assert "def resolve_workspace_root() -> Path:" not in api
