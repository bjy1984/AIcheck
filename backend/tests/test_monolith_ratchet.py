"""巨石棘轮（issue #12 A-2 / F-2）。

2026-08-07 审计记下 routes.py 30,490 行、repo.state 直写 82 处；
2026-08-13 复量 32,226 行、直写 117 处——六天又长了 1,736 行，其中不少是我
自己修 bug 时加的。一次性拆 32k 行是多日工程且会制造巨型 diff，棘轮先止血。

这些用例钉的是「棘轮真的会拦」——一个不会失败的护栏等于没有护栏。
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import monolith_baseline

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_baseline_file_is_committed_and_covers_the_tracked_files() -> None:
    """基线必须在版本库里，否则每个人量出来的口径都不一样。"""
    baseline = json.loads((BACKEND_ROOT / "monolith-baseline.json").read_text(encoding="utf-8"))
    for tracked in monolith_baseline.TRACKED_FILES:
        assert tracked in baseline, tracked
        assert baseline[tracked]["lines"] > 0


def test_current_metrics_do_not_exceed_the_baseline() -> None:
    """当前不许超过基线——这条红了就说明有人又往巨石里加东西了。"""
    baseline = json.loads((BACKEND_ROOT / "monolith-baseline.json").read_text(encoding="utf-8"))
    for name, values in monolith_baseline.current_metrics().items():
        for metric, value in values.items():
            was = int((baseline.get(name) or {}).get(metric, value))
            assert value <= was, f"{name}·{metric} 从 {was} 涨到 {value}"


def test_direct_state_write_pattern_catches_the_real_shapes() -> None:
    """直写模式要认得出真实写法。

    repo.state["x"].append(...) 绕过 repository 方法，也就绕过 revision 递增、
    审计留痕和字段校验——那不是难读，是会出错。认漏一种写法，棘轮就形同虚设。
    """
    pattern = monolith_baseline.DIRECT_WRITE_PATTERN
    for snippet in (
        'repo.state["documents"].append(item)',
        'repo.state["documents"].insert(0, item)',
        'repo.state["documents"].extend(items)',
        'repo.state[key].clear()',
        'repo.state["documents"] = []',
        'repo.state.setdefault("x", []).append(1)'.replace("repo.state.setdefault", "repo.state[k].setdefault"),
    ):
        assert pattern.search(snippet), snippet


def test_direct_write_pattern_does_not_flag_plain_reads() -> None:
    """只读访问不算直写——把读也算进去，指标就失去了区分度。"""
    pattern = monolith_baseline.DIRECT_WRITE_PATTERN
    for snippet in (
        'for item in repo.state["documents"]:',
        'value = repo.state["documents"][0]',
        'if repo.state["documents"] == []:',
    ):
        assert not pattern.search(snippet), snippet
