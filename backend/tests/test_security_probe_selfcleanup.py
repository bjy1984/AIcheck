"""安全探针必须真的清掉自己造的文档。

探针的 upload-session 用例会创建持久文档记录（即使从不 PUT 字节）。
清不掉的话每天累积僵尸——它们 OCR 永久排队，看起来像上传链路坏了
（2026-08-29 审计：先积到 22 份，修一版后仍以每天 5 份继续积到 25 份）。

两个坑都钉住：
1. 删除要 file:withdraw 权限，**admin 没有**（实测 403）——必须用上传者角色；
2. 走 raw_call 的用例（大载荷）同样建文档，也要登记。
"""

from __future__ import annotations

import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE = BACKEND_ROOT / "scripts" / "security_surface_probe.py"


def test_cleanup_does_not_rely_on_admin() -> None:
    source = PROBE.read_text(encoding="utf-8")
    body = source.split("def cleanup_created_docs", 1)[1].split("\ndef ", 1)[0]
    assert '"contractor"' in body, "必须用上传者角色删除，admin 无 file:withdraw"
    assert 'api(f"/api/projects/{PID}/documents/{doc_id}", "admin"' not in body


def test_cleanup_failure_is_reported_not_swallowed() -> None:
    """清不掉要出声——静默失败正是僵尸累积到 25 份都没人发现的原因。"""
    source = PROBE.read_text(encoding="utf-8")
    body = source.split("def cleanup_created_docs", 1)[1].split("\ndef ", 1)[0]
    assert "record(" in body, "清理失败必须记成检查项，否则探针会假装清干净了"


def test_every_upload_session_call_registers_created_docs() -> None:
    """包括走 raw_call 的大载荷用例。"""
    source = PROBE.read_text(encoding="utf-8")
    # 锚在代码而非注释上：「大载荷」三个字在文件头 docstring 里也出现
    huge_block = source.split("huge = json.dumps", 1)[1][:900]
    assert "_created_docs.append" in huge_block, "raw_call 建的文档也要登记"


def test_cleanup_runs_before_result_summary() -> None:
    """清理失败要能进入本次汇总。"""
    source = PROBE.read_text(encoding="utf-8")
    assert source.index("cleanup_created_docs()") < source.index("failed = [(s, d) for s, ok_, d in RESULTS")
