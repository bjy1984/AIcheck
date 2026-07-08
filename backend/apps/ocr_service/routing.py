from __future__ import annotations

from typing import Any

from apps.ocr_service.utils import parse_bool


TEXT_ENGINES = {"pymupdf_text_layer", "paddle_ocr_subprocess", "paddle_ocr_v6", "tesseract_cli", "docling_local"}
RASTER_TEXT_ENGINES = {"paddle_ocr_subprocess", "paddle_ocr_v6", "tesseract_cli"}
TABLE_ENGINES = {"pp_structure_v3", "opencv_table_grid_subprocess"}
SEAL_ENGINES = {"paddlex_seal_recognition", "agentdesign_seal_ocr_subprocess", "visual_seal_candidate_subprocess"}
FALLBACK_ENGINES = {"paddleocr_vl_1_6"}
DOCUMENT_LEVEL_ENGINES = {"pymupdf_text_layer", "docling_local", "paddleocr_vl_1_6"}
QUICK_MODE_DISABLED_ENGINES = {
    "agentdesign_seal_ocr_subprocess",
    "docling_local",
    "paddlex_seal_recognition",
}


def route_engine_variants(
    engine_name: str,
    variants: list[dict[str, Any]],
    *,
    profile: dict[str, Any],
    page_quality: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    quick_mode = parse_bool((options or {}).get("quickMode"), False) is True
    if quick_mode and engine_name in QUICK_MODE_DISABLED_ENGINES:
        return []
    remediation_mode = bool((options or {}).get("runRemediation"))
    if (
        engine_name in RASTER_TEXT_ENGINES
        and parse_bool((options or {}).get("enableRasterTextOcr"), True) is False
        and not remediation_mode
    ):
        return []
    if engine_name in TABLE_ENGINES and parse_bool((options or {}).get("enableTables"), True) is False:
        return []
    if engine_name in SEAL_ENGINES and parse_bool((options or {}).get("enableSeals"), True) is False:
        return []
    if engine_name in FALLBACK_ENGINES and parse_bool((options or {}).get("enableFallback"), True) is False:
        return []
    document_path = str((options or {}).get("documentPath") or "")
    if not variants:
        if engine_name in DOCUMENT_LEVEL_ENGINES and document_path.lower().endswith(".pdf"):
            return [synthetic_document_variant(document_path)]
        return []
    originals = variants_by_name(variants, "original") or [variants[0]]
    quality_by_page = {
        int(item.get("pageNo") or 1): (item.get("quality") if isinstance(item.get("quality"), dict) else {})
        for item in page_quality
        if isinstance(item, dict)
    }
    policy = profile.get("preprocessPolicy") or {}
    if remediation_mode:
        remediation_routed = remediation_crop_route(engine_name, variants)
        if remediation_routed:
            return remediation_routed
    if engine_name in {"pymupdf_text_layer", "docling_local"}:
        first = originals[0]
        if str(first.get("sourceType") or "").lower() == "pdf" or str(first.get("documentPath") or document_path).lower().endswith(".pdf"):
            return [document_variant(first)]
        if bool((options or {}).get("runAllVariants")):
            return originals
        return originals[:1]
    if engine_name in FALLBACK_ENGINES and document_path.lower().endswith(".pdf") and (
        bool((options or {}).get("runAllVariants"))
        or parse_bool((options or {}).get("forceFallbackOcr"), False) is True
    ):
        return [synthetic_document_variant(document_path)]
    if seal_engine_disabled(engine_name, profile):
        return []
    if bool((options or {}).get("runAllVariants")):
        return variants
    if engine_name == "pp_structure_v3":
        if table_engine_disabled(profile):
            return []
        return structure_variants(variants, quality_by_page, profile=profile)
    if engine_name == "opencv_table_grid_subprocess":
        return purpose_variants_by_page(variants, "table", quality_by_page, fallback=False)
    if engine_name in SEAL_ENGINES:
        if engine_name == "visual_seal_candidate_subprocess":
            if quick_mode:
                return originals[:1]
            return purpose_variants_by_page(variants, "seal", quality_by_page, fallback=True)
        return seal_text_variants(
            variants,
            quality_by_page,
            profile=profile,
            include_mask=engine_name == "paddlex_seal_recognition",
        )
    if engine_name in FALLBACK_ENGINES:
        if should_run_fallback(policy, merged_quality(quality_by_page), options=options):
            return originals
        return []
    if engine_name in TEXT_ENGINES:
        if quick_mode:
            return quick_text_variants_by_page(variants, quality_by_page)
        return text_variants_by_page(variants, quality_by_page)
    return originals


def seal_engine_disabled(engine_name: str, profile: dict[str, Any]) -> bool:
    if engine_name not in SEAL_ENGINES:
        return False
    seal_policy = ((profile.get("preprocessPolicy") or {}).get("seal") or {}) if isinstance(profile, dict) else {}
    required_seal = parse_bool(
        ((profile.get("sealRules") or {}) if isinstance(profile, dict) else {}).get("required"),
        False,
    ) is True
    default_enabled = required_seal
    if engine_name == "paddlex_seal_recognition" and not seal_policy_enabled(
        seal_policy,
        "enablePaddlexSeal",
        default=default_enabled,
    ):
        return True
    if engine_name == "agentdesign_seal_ocr_subprocess" and not seal_policy_enabled(
        seal_policy,
        "enableAgentdesignSeal",
        default=seal_policy_enabled(seal_policy, "enableSealTextRecognition", default=default_enabled),
    ):
        return True
    if engine_name == "visual_seal_candidate_subprocess" and not seal_policy_enabled(
        seal_policy,
        "enableColorCandidate",
        default=default_enabled,
    ):
        return True
    return False


def table_engine_disabled(profile: dict[str, Any]) -> bool:
    table_policy = ((profile.get("preprocessPolicy") or {}).get("table") or {}) if isinstance(profile, dict) else {}
    required_tables = profile.get("requiredTables") or []
    if "enabled" not in table_policy:
        return False
    return parse_bool(table_policy.get("enabled"), bool(required_tables)) is False


def seal_policy_enabled(policy: dict[str, Any], key: str, *, default: bool) -> bool:
    if key not in policy:
        return default
    return parse_bool(policy.get(key), default) is True


def remediation_crop_route(engine_name: str, variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if engine_name in TABLE_ENGINES:
        return remediation_crop_variants(variants, purpose="table")[:3]
    if engine_name in SEAL_ENGINES:
        return remediation_crop_variants(variants, purpose="seal")[:8]
    if engine_name in TEXT_ENGINES:
        field_crops = remediation_crop_variants(variants, purpose="field")[:10]
        seal_crops = remediation_crop_variants(variants, purpose="seal")[:8]
        return [*field_crops, *seal_crops]
    if engine_name in FALLBACK_ENGINES:
        return remediation_crop_variants(variants)[:8]
    return []


def remediation_crop_variants(variants: list[dict[str, Any]], purpose: str | None = None) -> list[dict[str, Any]]:
    crops = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and str(variant.get("source") or "") == "remediation_crop"
        and (purpose is None or str(variant.get("purpose") or "") == purpose)
    ]
    return sorted(crops, key=lambda item: (variant_page_no(item), str(item.get("variantId") or "")))


def variant_for_purpose(variants: list[dict[str, Any]], purpose: str) -> dict[str, Any] | None:
    return next((variant for variant in variants if variant.get("purpose") == purpose), None)


def variants_by_name(variants: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    suffix = f"_{name}"
    return [variant for variant in variants if str(variant.get("variantId") or "").endswith(suffix)]


def variant_page_no(variant: dict[str, Any]) -> int:
    try:
        return int(variant.get("pageNo"))
    except (TypeError, ValueError):
        pass
    variant_id = str(variant.get("variantId") or "")
    parts = variant_id.split("_", 2)
    if len(parts) >= 2 and parts[0] == "page":
        try:
            return int(parts[1])
        except ValueError:
            return 1
    return 1


def variants_for_page(variants: list[dict[str, Any]], page_no: int) -> list[dict[str, Any]]:
    return [variant for variant in variants if variant_page_no(variant) == page_no]


def original_for_page(variants: list[dict[str, Any]], page_no: int) -> dict[str, Any] | None:
    return next(
        (variant for variant in variants_for_page(variants, page_no) if str(variant.get("variantId") or "").endswith("_original")),
        None,
    )


def text_variants_by_page(variants: list[dict[str, Any]], quality_by_page: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    routed = []
    pages = sorted({variant_page_no(variant) for variant in variants})
    for page_no in pages:
        page_variants = variants_for_page(variants, page_no)
        quality = quality_by_page.get(page_no) or {}
        preferred = text_variant(page_variants, quality)
        original = original_for_page(variants, page_no)
        if preferred:
            routed.append(preferred)
        if original and original not in routed:
            routed.append(original)
    return routed


def quick_text_variants_by_page(variants: list[dict[str, Any]], quality_by_page: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    routed = []
    for page_no in sorted({variant_page_no(variant) for variant in variants}):
        page_variants = variants_for_page(variants, page_no)
        quality = quality_by_page.get(page_no) or {}
        routed.append(text_variant(page_variants, quality) or original_for_page(variants, page_no) or page_variants[0])
    return [variant for variant in routed if variant]


def structure_variants(
    variants: list[dict[str, Any]],
    quality_by_page: dict[int, dict[str, Any]],
    *,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    routed = []
    table_policy = ((profile.get("preprocessPolicy") or {}).get("table") or {}) if isinstance(profile, dict) else {}
    required_tables = profile.get("requiredTables") or []
    try:
        max_pages = int(table_policy.get("maxPages") or (4 if required_tables else 2))
    except (TypeError, ValueError):
        max_pages = 4 if required_tables else 2
    page_numbers = sorted({variant_page_no(variant) for variant in variants})
    if max_pages > 0:
        page_numbers = keep_required_edge_pages(page_numbers, [], max_pages)
    for page_no in page_numbers:
        page_variants = variants_for_page(variants, page_no)
        quality = quality_by_page.get(page_no) or {}
        preferred_names = (
            ["original", "deskew", "gray_clahe"]
            if quality.get("isLowQuality") or abs(float(quality.get("skewAngle") or 0.0)) > 0.8
            else ["original", "gray_clahe"]
        )
        page_routed = []
        for name in preferred_names:
            match = next((variant for variant in page_variants if str(variant.get("variantId") or "").endswith(f"_{name}")), None)
            if match and match not in page_routed:
                page_routed.append(match)
        routed.extend(page_routed[:2])
    return routed


def purpose_variants_by_page(
    variants: list[dict[str, Any]],
    purpose: str,
    quality_by_page: dict[int, dict[str, Any]],
    *,
    fallback: bool,
) -> list[dict[str, Any]]:
    routed = []
    for page_no in sorted({variant_page_no(variant) for variant in variants}):
        quality = quality_by_page.get(page_no) or {}
        purpose_variant = variant_for_page_purpose(variants, page_no, purpose)
        if purpose == "table" and not (
            quality.get("hasVisualTableCandidate") or quality.get("hasTableCandidate")
        ):
            continue
        if purpose == "seal" and not (
            quality.get("hasVisualSealCandidate") or quality.get("hasSealCandidate")
        ):
            continue
        match = purpose_variant
        if match:
            routed.append(match)
        elif fallback:
            original = original_for_page(variants, page_no)
            if original:
                routed.append(original)
    return routed


def seal_text_variants(
    variants: list[dict[str, Any]],
    quality_by_page: dict[int, dict[str, Any]],
    *,
    profile: dict[str, Any],
    include_mask: bool,
) -> list[dict[str, Any]]:
    all_pages = sorted({variant_page_no(variant) for variant in variants})
    if not all_pages:
        return []
    seal_policy = ((profile.get("preprocessPolicy") or {}).get("seal") or {}) if isinstance(profile, dict) else {}
    required_seal = parse_bool(
        ((profile.get("sealRules") or {}) if isinstance(profile, dict) else {}).get("required"),
        False,
    ) is True
    max_pages = int(seal_policy.get("maxPages") or (6 if required_seal else 2))
    candidate_pages = [
        page_no
        for page_no in all_pages
        if (quality_by_page.get(page_no) or {}).get("hasVisualSealCandidate")
    ]
    fallback_pages = [all_pages[0], all_pages[-1]] if required_seal else []
    ordered_pages = dedupe_page_order([*fallback_pages, *candidate_pages])
    selected_pages = keep_required_edge_pages(ordered_pages, fallback_pages, max(max_pages, 1))
    if not selected_pages and required_seal:
        selected_pages = keep_required_edge_pages(all_pages, fallback_pages, max(max_pages, 1))
    routed = []
    for page_no in selected_pages:
        original = original_for_page(variants, page_no)
        seal_variant = variant_for_page_purpose(variants, page_no, "seal")
        if original:
            routed.append(original)
        if include_mask and seal_variant and seal_variant not in routed:
            routed.append(seal_variant)
    return routed


def variant_for_page_purpose(variants: list[dict[str, Any]], page_no: int, purpose: str) -> dict[str, Any] | None:
    return next((variant for variant in variants_for_page(variants, page_no) if variant.get("purpose") == purpose), None)


def dedupe_page_order(page_numbers: list[int]) -> list[int]:
    seen = set()
    output = []
    for page_no in page_numbers:
        if page_no in seen:
            continue
        seen.add(page_no)
        output.append(page_no)
    return output


def keep_required_edge_pages(page_numbers: list[int], required_pages: list[int], limit: int) -> list[int]:
    if len(page_numbers) <= limit:
        return page_numbers
    selected = []
    for page_no in required_pages:
        if page_no not in selected:
            selected.append(page_no)
    for page_no in page_numbers:
        if len(selected) >= limit:
            break
        if page_no not in selected:
            selected.append(page_no)
    return selected


def document_variant(first: dict[str, Any]) -> dict[str, Any]:
    return {
        **first,
        "variantId": "document_original",
        "pageNo": None,
        "path": first.get("documentPath") or first.get("path"),
        "preprocessChain": ["document_original"],
        "purpose": "document",
        "source": "document",
        "engineScope": "document",
    }


def synthetic_document_variant(document_path: str) -> dict[str, Any]:
    return {
        "variantId": "document_original",
        "pageNo": None,
        "path": document_path,
        "documentPath": document_path,
        "sourceType": "pdf",
        "preprocessChain": ["document_original"],
        "purpose": "document",
        "source": "document",
        "engineScope": "document",
    }


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
        "hasTableCandidate": any(item.get("hasVisualTableCandidate") or item.get("hasTableCandidate") for item in qualities),
        "hasSealCandidate": any(item.get("hasVisualSealCandidate") or item.get("hasSealCandidate") for item in qualities),
    }


def should_run_fallback(policy: dict[str, Any], quality: dict[str, Any], *, options: dict[str, Any] | None = None) -> bool:
    fallback = policy.get("fallback") or {}
    configured = {str(item) for item in fallback.get("enableVlmWhen") or []}
    reasons = {str(item) for item in (options or {}).get("remediationReasons") or []}
    if configured and reasons and configured.intersection(reasons):
        return True
    return bool(configured) and bool(quality.get("isLowQuality"))
