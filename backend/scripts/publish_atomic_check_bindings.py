from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

from libs.business_pack import load_business_pack, validate_business_pack
from libs.review_orchestrator.execution import runtime_tool_catalog

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def binding_path(pack_id: str) -> Path:
    path = BACKEND_ROOT / "business_packs" / pack_id / "atomic_check_tool_bindings.yaml"
    if not path.is_file():
        raise RuntimeError(f"Atomic check binding file does not exist: {path}")
    return path


def validate_release(pack_id: str) -> dict[str, object]:
    pack = load_business_pack(pack_id)
    validation = validate_business_pack(pack)
    if not validation.get("ok"):
        raise RuntimeError("Business pack validation failed: " + "; ".join(validation.get("errors") or []))
    bindings = [item for item in pack.get("atomicCheckToolBindings") or [] if isinstance(item, dict)]
    declared_count = int((pack.get("atomicCheckToolBindingSet") or {}).get("atomicCheckCount") or 0)
    if not bindings or declared_count != len(bindings):
        raise RuntimeError(f"Binding count mismatch: declared={declared_count}, actual={len(bindings)}")
    invalid_statuses = sorted(
        {
            str(item.get("implementationStatus") or "")
            for item in bindings
            if str(item.get("implementationStatus") or "") not in {"implemented", "pilot_implemented"}
        }
    )
    if invalid_statuses:
        raise RuntimeError("Unreleasable implementationStatus values: " + ", ".join(invalid_statuses))
    available_tools = {str(item["name"]) for item in runtime_tool_catalog()}
    used_tools = {str(tool) for item in bindings for tool in item.get("tools") or []}
    missing_tools = sorted(used_tools - available_tools)
    if missing_tools:
        raise RuntimeError("Bindings reference unregistered tools: " + ", ".join(missing_tools))
    return {
        "bindingCount": len(bindings),
        "usedToolCount": len(used_tools),
        "businessPackVersion": pack.get("version"),
        "bindingSetVersion": (pack.get("atomicCheckToolBindingSet") or {}).get("version"),
    }


def publish(
    pack_id: str,
    *,
    approver: str,
    approval_ticket: str,
    expected_sha256: str,
    dry_run: bool,
) -> dict[str, object]:
    path = binding_path(pack_id)
    source = path.read_bytes()
    source_sha256 = hashlib.sha256(source).hexdigest()
    if source_sha256 != expected_sha256.lower().removeprefix("sha256:"):
        raise RuntimeError(f"Binding source hash changed: expected={expected_sha256}, actual={source_sha256}")
    release_evidence = validate_release(pack_id)
    document = yaml.safe_load(source) or {}
    binding_set = document.get("atomicCheckToolBindingSet")
    if not isinstance(binding_set, dict):
        raise RuntimeError("atomicCheckToolBindingSet is missing")
    published_at = datetime.now(UTC).isoformat()
    result = {
        "packId": pack_id,
        "path": str(path),
        "sourceSha256": source_sha256,
        "approver": approver,
        "approvalTicket": approval_ticket,
        "publishedAt": published_at,
        **release_evidence,
    }
    if dry_run:
        return {**result, "dryRun": True, "lifecycleStatus": binding_set.get("lifecycleStatus")}
    binding_set.update(
        {
            "lifecycleStatus": "published",
            "publishedAt": published_at,
            "approvedBy": approver,
            "approvalTicket": approval_ticket,
            "sourceSha256BeforePublication": source_sha256,
        }
    )
    rendered = yaml.safe_dump(document, allow_unicode=True, sort_keys=False).encode("utf-8")
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return {**result, "dryRun": False, "lifecycleStatus": "published"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a validated atomic-check tool binding set.")
    parser.add_argument("--pack-id", default="engineering_inspection_v1")
    parser.add_argument("--approver", required=True)
    parser.add_argument("--approval-ticket", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(
        publish(
            args.pack_id,
            approver=args.approver,
            approval_ticket=args.approval_ticket,
            expected_sha256=args.expected_sha256,
            dry_run=args.dry_run,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
