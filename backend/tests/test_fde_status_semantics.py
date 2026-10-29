import pytest

from libs.fde_console_views import FDE_STATUS_CATALOG, fde_status_code, fde_status_summary


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("完成", "completed"),
        ("已完成", "completed"),
        ("completed", "completed"),
        ("未完成", "unknown"),
        ("not_completed", "unknown"),
        ("unknown", "unknown"),
        ("future_status", "unknown"),
        (None, "unknown"),
        ("not_started", "not_started"),
        ("未开始", "not_started"),
        ("queued", "in_progress"),
        ("in_progress", "in_progress"),
        ("failed", "failed"),
        ("failed_to_start", "failed_to_start"),
        ("pending_human_review", "needs_attention"),
        ("waiting_human_review", "needs_attention"),
        ("needs_human_confirmation", "needs_attention"),
        ("待人工确认", "needs_attention"),
        ("pending_approval", "needs_attention"),
    ],
)
def test_known_run_states_and_unknown_values_remain_distinct(raw, expected):
    assert fde_status_code(raw) == expected


def test_dashboard_counts_match_completed_list_status_without_hiding_unknowns():
    rows = [{"status": "完成"}, {"status": "not_started"}, {}, {"status": "未完成"}]
    result = fde_status_summary(rows)
    assert result["completed"] == 1
    assert result["not_started"] == 1
    assert result["unknown"] == 2
    assert sum(result.values()) == len(rows)
    assert any(row["code"] == "unknown" and row["tone"] == "info" for row in FDE_STATUS_CATALOG)
