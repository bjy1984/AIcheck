"""业务口径的「今天」。

## 为什么不能用 date.today()

2026-08-14 实测：宿主机 CST +0800，**容器 UTC +0000**。裸用 `date.today()`
拿到的是 UTC 日期，于是每天 00:00–08:00 这 8 小时里，它比业务日期少一天。

落到业务上：一张 2026-08-14 到期的焊工证，在 08-15 凌晨那段时间会被判成
仍然有效——有效期判定整整差一天。同类还有规则版本切换日
（`review_date >= date(2026, 8, 1)`）和标准现行性核验。

这个 bug 是 ruff 的 DTZ011 报出来的，但它不是一条 lint 洁癖：
仓库里本来就有正确的时区口径（server_time 用 SERVER_TZ），
这 5 处只是各写各的，绕过了它。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from libs.contracts.responses import SERVER_TZ, business_today


def test_与_server_time_同一个时区口径():
    """别再各写各的——两个函数给出的日期必须一致。"""
    assert business_today() == datetime.now(SERVER_TZ).date()


def test_跨零点那八小时里不等于_utc_日期(monkeypatch: pytest.MonkeyPatch):
    """构造 UTC 与业务日期真正不同的时刻，确认取的是业务日期。

    UTC 2026-08-14 17:30 = Asia/Shanghai 2026-08-15 01:30。
    裸 date.today() 在 UTC 容器里会给 08-14，业务上该是 08-15。
    """
    frozen_utc = datetime(2026, 8, 14, 17, 30, tzinfo=timezone.utc)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_utc.astimezone(tz) if tz else frozen_utc.replace(tzinfo=None)

    monkeypatch.setattr("libs.contracts.responses.datetime", _FrozenDatetime)
    assert frozen_utc.date() == date(2026, 8, 14), "前提：UTC 日期是 14 号"
    assert business_today() == date(2026, 8, 15), "业务日期该是 15 号"


def test_焊工证有效期判定用业务日期(monkeypatch: pytest.MonkeyPatch):
    """最贵的那处：证书到期日 == 业务今天时必须仍判有效，
    而按 UTC 会早一天判成 expired（或晚一天仍判 valid）。"""
    from libs.ocr import welder_certificate_tool as tool

    today = business_today()
    # validity_status 收的是点分格式（%Y.%m.%d），不是 ISO
    assert tool.validity_status(today.strftime("%Y.%m.%d")) == "valid"
    assert tool.validity_status((today - timedelta(days=1)).strftime("%Y.%m.%d")) == "expired"
    # 明天到期当然还有效——这条钉住的是「到期当天不算过期」的边界
    assert tool.validity_status((today + timedelta(days=1)).strftime("%Y.%m.%d")) == "valid"
