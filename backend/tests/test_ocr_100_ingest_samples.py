from __future__ import annotations

import json

from scripts.ocr_100_corpus import build_corpus_report
from scripts.ocr_100_ingest_samples import build_sample_queue


def test_ocr_100_ingest_samples_builds_labeling_queue_and_filters_standards(tmp_path) -> None:
    samples = tmp_path / "samples"
    samples.mkdir()
    material = samples / "材质证书.pdf"
    qualification = samples / "资质证书.pdf"
    standard = samples / "GB 50235-2010 工业金属管道工程施工规范.pdf"
    image = samples / "现场盖章.jpg"
    material.write_bytes(b"%PDF-1.4 material")
    qualification.write_bytes(b"%PDF-1.4 qualification")
    standard.write_bytes(b"%PDF-1.4 standard")
    image.write_bytes(b"\xff\xd8\xff")

    payload = build_sample_queue([samples], base_dir=tmp_path)
    cases = payload["cases"]

    assert payload["summary"]["cases"] == 3
    assert {case["scenario"] for case in cases} == {
        "quality_certificate_profile",
        "qualification_certificate_profile",
        "seal_text_profile",
    }
    assert all(case["collectionStatus"] == "needs_labeling" for case in cases)
    assert all(case["source"]["sha256"].startswith("sha256:") for case in cases)
    assert all("replace-with" in json.dumps(case["expected"], ensure_ascii=False) for case in cases)
    assert all("GB 50235" not in case["source"]["fileName"] for case in cases)


def test_ocr_100_ingest_queue_does_not_certify_placeholder_evidence(tmp_path) -> None:
    sample = tmp_path / "材质证书.pdf"
    sample.write_bytes(b"%PDF-1.4 material")

    payload = build_sample_queue([sample], base_dir=tmp_path)
    eval_set = tmp_path / "queue.json"
    eval_set.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    report = build_corpus_report([eval_set], require_real_samples=True)
    codes = {item["code"] for item in report["failures"]}

    assert payload["cases"][0]["collectionStatus"] == "needs_labeling"
    assert "OCR_100_CORPUS_EXPECTED_EVIDENCE_MISSING" in codes
    assert "OCR_100_CORPUS_SYNTHETIC_CASE" not in codes


def test_ocr_100_ingest_samples_can_copy_and_force_scenario(tmp_path) -> None:
    source = tmp_path / "unknown.pdf"
    source.write_bytes(b"%PDF-1.4 unknown")
    copied = tmp_path / "corpus_assets"

    payload = build_sample_queue(
        [source],
        base_dir=tmp_path,
        copy_to=copied,
        scenario_override="ndt_rt_profile",
    )
    case = payload["cases"][0]

    assert case["scenario"] == "ndt_rt_profile"
    assert case["source"]["classification"]["method"] == "override"
    assert case["source"]["originalPath"] == str(source.resolve())
    assert (tmp_path / case["source"]["path"]).exists()


def test_ocr_100_ingest_samples_uses_manifest_for_numeric_scan_names(tmp_path) -> None:
    samples = tmp_path / "Scan"
    samples.mkdir()
    rt_pdf = samples / "20260623105636.pdf"
    heic = samples / "IMG_6509.heic"
    rt_pdf.write_bytes(b"%PDF-1.4 rt")
    heic.write_bytes(b"heic-photo")
    manifest = {
        "samples": [
            {"fileName": "20260623105636.pdf", "scenario": "ndt_rt_profile", "notes": "RT report"},
            {"fileName": "IMG_6509.heic", "scenario": "piping_table_profile", "notes": "piping list photo"},
        ]
    }

    payload = build_sample_queue([samples], base_dir=tmp_path, manifest={item["fileName"]: item for item in manifest["samples"]})

    cases = {case["source"]["fileName"]: case for case in payload["cases"]}
    assert cases["20260623105636.pdf"]["scenario"] == "ndt_rt_profile"
    assert cases["20260623105636.pdf"]["source"]["classification"]["method"] == "manifest"
    assert cases["20260623105636.pdf"]["source"]["notes"] == "RT report"
    assert cases["IMG_6509.heic"]["scenario"] == "piping_table_profile"
    assert cases["IMG_6509.heic"]["source"]["mimeType"] == "image/heic"
