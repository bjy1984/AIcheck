from __future__ import annotations

from apps.ocr_service.service import apply_parse_options_to_profile


def test_all_ocr_profiles_are_capped_at_1920(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_OCR_MAX_LONG_SIDE", "1920")
    profile = {
        "preprocessPolicy": {
            "renderDpi": 400,
            "maxLongSide": 2800,
            "textDetLimitSideLen": 3200,
            "ocr": {"textDetLimitSideLen": 3200},
        }
    }

    adjusted = apply_parse_options_to_profile(
        profile,
        {"maxLongSide": 4096, "textDetLimitSideLen": 4096},
    )
    policy = adjusted["preprocessPolicy"]

    assert policy["maxLongSide"] == 1920
    assert policy["textDetLimitSideLen"] == 1920
    assert policy["ocr"]["textDetLimitSideLen"] == 1920


def test_resolution_cap_can_only_be_lowered_by_runtime(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_OCR_MAX_LONG_SIDE", "1600")
    profile = {"preprocessPolicy": {"maxLongSide": 1800}}

    adjusted = apply_parse_options_to_profile(profile, {"maxLongSide": 1920})

    assert adjusted["preprocessPolicy"]["maxLongSide"] == 1600
