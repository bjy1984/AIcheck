"""Cross-check public standard identity without treating citations as document identity."""
import re
from libs.knowledge_retrieval import canonical_standard_text, standard_refs_from_text, STANDARD_REF_RE


def identity_check(file: dict, record: dict | None) -> dict:
    # The leading identifier names the document; later references can describe
    # replacement standards and must never make this file match that newer edition.
    filename_refs = standard_refs_from_text(file.get("fileName", ""))[:1]
    record = record or {}
    evidence = []
    code = record.get("identity", {}).get("standardCode", {})
    for source in code.get("sources", []):
        if source.get("sourceType") in {"new_mineru", "new_mineru_semantic", "visual_extraction", "standard_catalog", "legacy_ocr"}:
            for ref in standard_refs_from_text(source.get("value", "")):
                evidence.append({"ref": ref, "basis": "canonical_source", "pageNo": source.get("pageNo")})
    # Canonical values can be supplied independently of the provenance list.
    # Check conflicts, but do not claim that a value alone proves its source.
    selected_refs = standard_refs_from_text(code.get("value", ""))
    cover = [b for b in record.get("blocks", []) if b.get("pageNo") == 1]
    for block in cover:
        for line in str(block.get("text") or "").splitlines():
            normalized = canonical_standard_text(line).strip()
            # Standalone identifier on cover only. Excludes 'replaces ...' and
            # normative-reference paragraphs, which identify other standards.
            if STANDARD_REF_RE.fullmatch(normalized):
                for ref in standard_refs_from_text(normalized):
                    evidence.append({"ref": ref, "basis": "cover_identifier", "pageNo": 1})
    versions = record.get("version", {}).get("edition", {})
    years = [str(s.get("value")) for s in versions.get("sources", [])
             if s.get("sourceType") != "filename_inference" and re.fullmatch(r"(?:19|20)\d{2}", str(s.get("value", "")))]
    selected_year = str(versions.get("value", ""))
    if re.fullmatch(r"(?:19|20)\d{2}", selected_year):
        years.append(selected_year)

    def compatible(left, right):
        return (left["prefix"], left["number"]) == (right["prefix"], right["number"]) and (
            not left["year"] or not right["year"] or left["year"] == right["year"])

    refs = [e["ref"] for e in evidence] + selected_refs
    conflict = bool(filename_refs) and (
        any(not any(compatible(ref, name) for name in filename_refs) for ref in refs)
        or any(name["year"] and year != name["year"] for name in filename_refs for year in years)
    )
    confirmed = bool(filename_refs) and all(any(
        compatible(name, e["ref"]) and (not name["year"] or e["ref"]["year"] == name["year"])
        for e in evidence) for name in filename_refs)
    return {"status": "conflict" if conflict else "verified" if confirmed else "unverified",
            "filenameReferences": filename_refs, "evidence": evidence,
            "manualConfirmationRequired": conflict or not confirmed}


def matches_requested_identity(requested: list, check: dict) -> bool:
    return check["status"] != "conflict" and any(
        wanted["prefix"] == actual["prefix"] and wanted["number"] == actual["number"]
        and (not wanted["year"] or wanted["year"] == actual["year"])
        for wanted in requested for actual in check["filenameReferences"])
