from __future__ import annotations

from typing import Any


TEXT_ENGINES = {"pymupdf_text_layer", "paddle_ocr_subprocess", "paddle_ocr_v6", "docling_local"}
TABLE_ENGINES = {"pp_structure_v3", "opencv_table_grid_subprocess"}
SEAL_ENGINES = {"paddlex_seal_recognition", "agentdesign_seal_ocr_subprocess", "visual_seal_candidate_subprocess"}
FALLBACK_ENGINES = {"paddleocr_vl_1_6"}


def route_engine_variants(
    engine_name: str,
    variants: list[dict[str, Any]],
    *,
    profile: dict[str, Any],
    page_quality: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not variants:
        return []
    if bool((options or {}).get("runAllVariants")):
        return variants
    by_id = {variant.get("variantId"): variant for variant in variants}
    original = by_id.get("page_1_original") or variants[0]
    quality = (page_quality[0].get("quality") if page_quality else {}) or {}
    policy = profile.get("preprocessPolicy") or {}
    if engine_name in TABLE_ENGINES:
        preferred = variant_for_purpose(variants, "table") if quality.get("hasTableCandidate") else None
        return [preferred or original]
    if engine_name in SEAL_ENGINES:
        preferred = variant_for_purpose(variants, "seal") if engine_name == "paddlex_seal_recognition" else original
        return [preferred or original]
    if engine_name in FALLBACK_ENGINES:
        if should_run_fallback(policy, quality):
            return [original]
        return []
    if engine_name in TEXT_ENGINES:
        if engine_name in {"pymupdf_text_layer", "docling_local"}:
            return [original]
        if not bool((options or {}).get("useEnhancedTextVariants")):
            return [original]
        preferred = text_variant(variants, quality)
        return [preferred or original]
    return [original]


def variant_for_purpose(variants: list[dict[str, Any]], purpose: str) -> dict[str, Any] | None:
    return next((variant for variant in variants if variant.get("purpose") == purpose), None)


def text_variant(variants: list[dict[str, Any]], quality: dict[str, Any]) -> dict[str, Any] | None:
    if quality.get("isLowQuality"):
        for variant_id in ["page_1_gray_clahe", "page_1_deskew", "page_1_adaptive_threshold"]:
            match = next((variant for variant in variants if variant.get("variantId") == variant_id), None)
            if match:
                return match
    return next((variant for variant in variants if variant.get("variantId") == "page_1_original"), variants[0] if variants else None)


def should_run_fallback(policy: dict[str, Any], quality: dict[str, Any]) -> bool:
    fallback = policy.get("fallback") or {}
    return bool(fallback.get("enableVlmWhen")) and bool(quality.get("isLowQuality"))
