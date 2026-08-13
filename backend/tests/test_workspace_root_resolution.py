"""本地上传文件的根目录解析（线上审计 M-1）。

线上 66 个真实文件（507 MB）的 storageKey 是 local://output/document_uploads/...，
但容器里全部解析失败：

    WORKSPACE_ROOT = Path(__file__).parents[3]
      本地开发 backend/apps/api/routes.py → 仓库根，output/ 在其下   ✓
      容器内   /app/apps/api/routes.py     → /，而文件在 /app/output/  ✗

少一层目录，local_storage_path() 就返回 /output/... 这个不存在的路径，
project_document_local_original_path() 一律返回 None，于是预览地址退回把内部
local:// 串下发给浏览器——浏览器当然取不到，界面只能报「无法预览」。

靠目录层数倒推是这个 bug 的根源：它把「代码放在哪一层」当成了不变量。
"""

from __future__ import annotations

import pathlib

import apps.api.routes as routes_module


def test_explicit_override_wins(monkeypatch, tmp_path: pathlib.Path) -> None:
    """部署环境可以直接指定，不必让代码去猜。"""
    monkeypatch.setenv("AICHECK_WORKSPACE_ROOT", str(tmp_path))
    assert routes_module.resolve_workspace_root() == tmp_path.resolve()


def test_falls_back_to_the_ancestor_that_actually_has_output(monkeypatch) -> None:
    """没有显式配置时，判据是「哪一层真的有 output/」而不是「往上数几层」。

    这正是容器与本地开发的差别所在：两边代码深度不同，但 output/ 的位置
    都能被这条判据找到。
    """
    monkeypatch.delenv("AICHECK_WORKSPACE_ROOT", raising=False)
    root = routes_module.resolve_workspace_root()
    assert (root / "output").is_dir(), f"解析出的根目录下没有 output/：{root}"


def test_local_storage_key_resolves_to_a_real_path(monkeypatch, tmp_path: pathlib.Path) -> None:
    """端到端：local:// 键必须能解析到真实文件。"""
    monkeypatch.setenv("AICHECK_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(routes_module, "WORKSPACE_ROOT", tmp_path.resolve())
    target = tmp_path / "output" / "document_uploads" / "P-1" / "V1" / "a.docx"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    resolved = routes_module.local_storage_path(
        "local://output/document_uploads/P-1/V1/a.docx"
    )
    assert resolved is not None
    assert resolved.is_file(), f"解析到了不存在的路径：{resolved}"


def test_path_traversal_is_still_blocked(monkeypatch, tmp_path: pathlib.Path) -> None:
    """放宽根目录判定不能放宽越界防护。"""
    monkeypatch.setattr(routes_module, "WORKSPACE_ROOT", tmp_path.resolve())
    assert routes_module.local_storage_path("local://../../etc/passwd") is None


def test_non_local_keys_are_ignored(monkeypatch, tmp_path: pathlib.Path) -> None:
    """minio:// 走对象存储，不该被当成本地路径。"""
    monkeypatch.setattr(routes_module, "WORKSPACE_ROOT", tmp_path.resolve())
    assert routes_module.local_storage_path("minio://documents/x") is None
    assert routes_module.local_storage_path(None) is None
