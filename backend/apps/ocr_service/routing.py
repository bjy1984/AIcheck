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
    originals = variants_by_name(variants, "original") or [variants[0]]
    quality_by_page = {
        int(item.get("pageNo") or 1): (item.get("quality") if isinstance(item.get("quality"), dict) else {})
        for item in page_quality
        if isinstance(item, dict)
    }
    policy = profile.get("preprocessPolicy") or {}
    if engine_name == "pp_structure_v3":
        return structure_variants(variants, quality_by_page)
    if engine_name == "opencv_table_grid_subprocess":
        return purpose_variants_by_page(variants, "table", quality_by_page, fallback=False)
    if engine_name in SEAL_ENGINES:
        if engine_name in {"paddlex_seal_recognition", "visual_seal_candidate_subprocess"}:
            return purpose_variants_by_page(variants, "seal", quality_by_page, fallback=True)
        return originals
    if engine_name in FALLBACK_ENGINES:
        if should_run_fallback(policy, merged_quality(quality_by_page), options=options):
            return originals
        return []
    if engine_name in TEXT_ENGINES:
        if engine_name in {"pymupdf_text_layer", "docling_local"}:
            return originals[:1]
        return text_variants_by_page(variants, quality_by_page)
    return originals


def variant_for_purpose(variants: list[dict[str, Any]], purpose: str) -> dict[str, Any] | None:
    return next((variant for variant in variants if variant.get("purpose") == purpose), None)


def variants_by_name(variants: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    suffix = f"_{name}"
    return [variant for variant in variants if str(variant.get("variantId") or "").endswith(suffix)]


def variants_for_page(variants: list[dict[str, Any]], page_no: int) -> list[dict[str, Any]]:
    return [variant for variant in variants if int(variant.get("pageNo") or 1) == page_no]


def original_for_page(variants: list[dict[str, Any]], page_no: int) -> dict[str, Any] | None:
    return next(
        (variant for variant in variants_for_page(variants, page_no) if str(variant.get("variantId") or "").endswith("_original")),
        None,
    )


def text_variants_by_page(variants: list[dict[str, Any]], quality_by_page: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    routed = []
    pages = sorted({int(variant.get("pageNo") or 1) for variant in variants})
    for page_no in pages:
        page_variants = variants_for_page(variants, page_no)
        quality = quality_by_page.get(page_no) or {}
        preferred = text_variant(page_variants, quality)
        original = original_for_page(variants, page_no)
        if preferred:
            routed.append(preferred)
        if original and original not in routed and not quality.get("isLowQuality"):
            routed.append(original)
    return routed


def structure_variants(variants: list[dict[str, Any]], quality_by_page: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    routed = []
    for page_no in sorted({int(variant.get("pageNo") or 1) for variant in variants}):
        page_variants = variants_for_page(variants, page_no)
        quality = quality_by_page.get(page_no) or {}
        preferred_names = ["original", "deskew", "gray_clahe"] if quality.get("isLowQuality") else ["original", "gray_clahe"]
        for name in preferred_names:
            match = next((variant for variant in page_variants if str(variant.get("variantId") or "").endswith(f"_{name}")), None)
            if match and match not in routed:
                routed.append(match)
                break
    return routed


def purpose_variants_by_page(
    variants: list[dict[str, Any]],
    purpose: str,
    quality_by_page: dict[int, dict[str, Any]],
    *,
    fallback: bool,
) -> list[dict[str, Any]]:
    routed = []
    for page_no in sorted({int(variant.get("pageNo") or 1) for variant in variants}):
        quality = quality_by_page.get(page_no) or {}
        if purpose == "table" and not quality.get("hasTableCandidate"):
            continue
        if purpose == "seal" and not quality.get("hasSealCandidate"):
            continue
        match = next((variant for variant in variants_for_page(variants, page_no) if variant.get("purpose") == purpose), None)
        if match:
            routed.append(match)
        elif fallback:
            original = original_for_page(variants, page_no)
            if original:
                routed.append(original)
    return routed


def text_variant(variants: list[dict[str, Any]], quality: dict[str, Any]) -> dict[str, Any] | None:
    if quality.get("isLowQuality"):
        for name in ["gray_clahe", "deskew", "adaptive_threshold"]:
            match = next((variant for variant in variants if str(variant.get("variantId") or "").endswith(f"_{name}")), None)
            if match:
                return match
    for name in ["gray_clahe", "original"]:
        match = next((variant for variant in variants if str(variant.get("variantId") or "").endswith(f"_{name}")), None)
        if match:
            return match
    return variants[0] if variants else None


def merged_quality(quality_by_page: dict[int, dict[str, Any]]) -> dict[str, Any]:
    qualities = list(quality_by_page.values())
    return {
        "isLowQuality": any(item.get("isLowQuality") for item in qualities),
        "hasTableCandidate": any(item.get("hasTableCandidate") for item in qualities),
        "hasSealCandidate": any(item.get("hasSealCandidate") for item in qualities),
    }


def should_run_fallback(policy: dict[str, Any], quality: dict[str, Any], *, options: dict[str, Any] | None = None) -> bool:
    fallback = policy.get("fallback") or {}
    configured = {str(item) for item in fallback.get("enableVlmWhen") or []}
    reasons = {str(item) for item in (options or {}).get("remediationReasons") or []}
    if configured and reasons and configured.intersection(reasons):
        return True
    return bool(configured) and bool(quality.get("isLowQuality"))
