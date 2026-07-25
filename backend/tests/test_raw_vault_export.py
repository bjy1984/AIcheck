from __future__ import annotations

import io
import json
import zipfile

from libs.raw_vault import InMemoryRawVaultStore, RawCapture, RawCaptureContext
from libs.raw_vault_export import build_raw_vault_export, verify_export_bytes


def test_export_round_trip_preserves_payload_and_verifies_chain() -> None:
    store = InMemoryRawVaultStore()
    capture = RawCapture(store=store)
    context = RawCaptureContext("TENANT-A", "RRUN-1", review_run_id="RRUN-1")
    original = b'{ "full": "\xe5\x8e\x9f\xe6\x96\x87" }\n'
    capture.capture_bytes(context, "llm.response.received", original, "application/json")

    archive = build_raw_vault_export(
        store.events_for_run("TENANT-A", "RRUN-1"),
        payload_loader=store.payload_for,
    )

    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        manifest = json.loads(package.read("manifest.json"))
        assert package.read(manifest["payloads"][0]["path"]) == original
    assert verify_export_bytes(archive).status == "verified"


def test_export_verifier_detects_modified_payload() -> None:
    store = InMemoryRawVaultStore()
    capture = RawCapture(store=store)
    context = RawCaptureContext("TENANT-A", "RRUN-1")
    capture.capture_bytes(context, "llm.response.received", b"original", "application/octet-stream")
    archive = build_raw_vault_export(
        store.events_for_run("TENANT-A", "RRUN-1"),
        payload_loader=store.payload_for,
    )

    source = zipfile.ZipFile(io.BytesIO(archive))
    target_bytes = io.BytesIO()
    with zipfile.ZipFile(target_bytes, "w") as target:
        for name in source.namelist():
            data = b"changed" if name.startswith("payloads/") else source.read(name)
            target.writestr(name, data)

    assert verify_export_bytes(target_bytes.getvalue()).status == "hash_mismatch"
