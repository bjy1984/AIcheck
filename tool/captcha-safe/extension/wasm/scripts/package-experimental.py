#!/usr/bin/env python3
"""Create and verify a deterministic, unsigned experimental WASM review package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.dont_write_bytecode = True

PACKAGE_MANIFEST = "EXPERIMENTAL-WASM-MANIFEST.json"
WASM_NAME = "captcha_solver.wasm"
LOADER_NAME = "captcha-solver-loader.mjs"
PACKAGE_NAMES = (PACKAGE_MANIFEST, LOADER_NAME, WASM_NAME)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
EXPECTED_EXTERNAL_ATTR = (stat.S_IFREG | 0o644) << 16
MAX_WASM_BYTES = 32 * 1024 * 1024
MAX_LOADER_BYTES = 1024 * 1024
MAX_METADATA_BYTES = 256 * 1024
MAX_PACKAGE_BYTES = 40 * 1024 * 1024
SHA256_LENGTH = 64
ALGORITHM_ID = "captcha-safe-canny-like-ncc-v1"


class ExperimentalPackageError(RuntimeError):
    """An experimental package is malformed, inconsistent, or unsafe."""


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExperimentalPackageError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ExperimentalPackageError(f"non-finite JSON number: {value}")


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExperimentalPackageError("value is not canonical JSON") from exc


def _parse_json(data: bytes, label: str) -> Any:
    if not data or len(data) > MAX_METADATA_BYTES:
        raise ExperimentalPackageError(f"{label} is empty or oversized")
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ExperimentalPackageError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ExperimentalPackageError(f"{label} is not strict UTF-8 JSON") from exc


def _read_regular(path: Path, maximum: int, label: str) -> bytes:
    path = Path(path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise ExperimentalPackageError(f"cannot inspect {label}: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ExperimentalPackageError(f"{label} must be a regular non-symlink file")
    if info.st_size <= 0 or info.st_size > maximum:
        raise ExperimentalPackageError(f"{label} is empty or oversized")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            current = os.fstat(handle.fileno())
            if not stat.S_ISREG(current.st_mode) or current.st_size != info.st_size:
                raise ExperimentalPackageError(f"{label} changed while being read")
            data = handle.read(maximum + 1)
    except ExperimentalPackageError:
        raise
    except OSError as exc:
        raise ExperimentalPackageError(f"cannot read {label}: {path}") from exc
    if len(data) != info.st_size or len(data) > maximum:
        raise ExperimentalPackageError(f"{label} changed or is oversized")
    return data


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _exact_fields(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ExperimentalPackageError(f"{label} schema is invalid")
    return value


def _validated_build_metadata(value: Any, wasm_digest: str) -> Mapping[str, Any]:
    fields = {
        "abiVersion",
        "algorithmId",
        "artifact",
        "artifactSha256",
        "compilerKind",
        "compilerPath",
        "compilerVersion",
        "containsImageCodecs",
        "containsOnnx",
        "containsOpenCv",
        "fixedMemoryBytes",
        "headerSha256",
        "linkerPath",
        "linkerVersion",
        "profile",
        "reproducibleCommand",
        "schemaVersion",
        "solverReadiness",
        "sourceDateEpoch",
        "sourceSha256",
    }
    metadata = _exact_fields(value, fields, "build metadata")
    expected_scalars = {
        "schemaVersion": 1,
        "profile": "DEVELOPMENT_ONLY_MINIMAL_C11",
        "solverReadiness": "PENDING",
        "abiVersion": 1,
        "algorithmId": ALGORITHM_ID,
        "artifactSha256": wasm_digest,
        "fixedMemoryBytes": 16_777_216,
        "sourceDateEpoch": 0,
        "containsOpenCv": False,
        "containsImageCodecs": False,
        "containsOnnx": False,
    }
    for field, expected in expected_scalars.items():
        if type(metadata[field]) is not type(expected) or metadata[field] != expected:
            raise ExperimentalPackageError(f"build metadata {field} is invalid")
    for field in (
        "artifact",
        "compilerKind",
        "compilerPath",
        "compilerVersion",
        "linkerPath",
        "linkerVersion",
        "reproducibleCommand",
    ):
        if not isinstance(metadata[field], str) or not metadata[field]:
            raise ExperimentalPackageError(f"build metadata {field} is invalid")
    for field in ("sourceSha256", "headerSha256"):
        if not _is_digest(metadata[field]):
            raise ExperimentalPackageError(f"build metadata {field} is invalid")
    return metadata


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = EXPECTED_EXTERNAL_ATTR
    return info


def _package_manifest(
    wasm: bytes, loader: bytes, metadata: Mapping[str, Any]
) -> bytes:
    records = [
        {"path": LOADER_NAME, "sha256": _digest(loader), "size": len(loader)},
        {"path": WASM_NAME, "sha256": _digest(wasm), "size": len(wasm)},
    ]
    value = {
        "schemaVersion": 1,
        "artifact": "captcha-safe-experimental-wasm",
        "status": "EXPERIMENTAL_UNSIGNED",
        "signed": False,
        "integrityOnlyNotAuthenticity": True,
        "solverReadiness": "PENDING",
        "actionAuthorized": False,
        "opencvParity": False,
        "abiVersion": 1,
        "algorithmId": ALGORITHM_ID,
        "fixedMemoryBytes": 16_777_216,
        "sourceSha256": metadata["sourceSha256"],
        "headerSha256": metadata["headerSha256"],
        "compiler": {
            "kind": metadata["compilerKind"],
            "version": metadata["compilerVersion"],
            "linkerVersion": metadata["linkerVersion"],
            "sourceDateEpoch": metadata["sourceDateEpoch"],
        },
        "payloadDigest": _digest(_canonical(records)),
        "files": records,
    }
    return _canonical(value) + b"\n"


def build_package(wasm_path: Path, metadata_path: Path, loader_path: Path, output: Path) -> str:
    wasm = _read_regular(wasm_path, MAX_WASM_BYTES, "WASM artifact")
    loader = _read_regular(loader_path, MAX_LOADER_BYTES, "WASM loader")
    if b"fetch(" in loader or b"importScripts(" in loader:
        raise ExperimentalPackageError("WASM loader may not fetch or import remote code")
    metadata_data = _read_regular(metadata_path, MAX_METADATA_BYTES, "build metadata")
    metadata = _validated_build_metadata(
        _parse_json(metadata_data, "build metadata"), _digest(wasm)
    )
    manifest = _package_manifest(wasm, loader, metadata)

    output = Path(output)
    source_root = Path(__file__).resolve().parents[1]
    resolved_output = output.resolve()
    if resolved_output == source_root or source_root in resolved_output.parents:
        raise ExperimentalPackageError("experimental package output must be outside source root")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(_zip_info(PACKAGE_MANIFEST), manifest)
            archive.writestr(_zip_info(LOADER_NAME), loader)
            archive.writestr(_zip_info(WASM_NAME), wasm)
        verify_package(temporary)
        os.chmod(temporary, 0o644)
        os.replace(temporary, output)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return _digest(_read_regular(output, MAX_PACKAGE_BYTES, "experimental package"))


def verify_package(package_path: Path) -> Mapping[str, Any]:
    _read_regular(package_path, MAX_PACKAGE_BYTES, "experimental package")
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            if archive.namelist() != list(PACKAGE_NAMES) or archive.comment:
                raise ExperimentalPackageError("experimental package entries are invalid")
            entries: dict[str, bytes] = {}
            for entry in archive.infolist():
                if (
                    entry.date_time != FIXED_ZIP_TIME
                    or entry.create_system != 3
                    or entry.create_version != 20
                    or entry.extract_version != 20
                    or entry.external_attr != EXPECTED_EXTERNAL_ATTR
                    or entry.compress_type != zipfile.ZIP_STORED
                    or entry.compress_size != entry.file_size
                    or entry.flag_bits != 0
                    or entry.internal_attr != 0
                    or entry.volume != 0
                    or entry.extra
                    or entry.comment
                ):
                    raise ExperimentalPackageError("experimental package metadata is invalid")
                entries[entry.filename] = archive.read(entry)
    except ExperimentalPackageError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
        raise ExperimentalPackageError("experimental package is not a valid ZIP") from exc
    manifest_data = entries[PACKAGE_MANIFEST]
    manifest = _parse_json(manifest_data, PACKAGE_MANIFEST)
    if manifest_data != _canonical(manifest) + b"\n":
        raise ExperimentalPackageError("experimental package manifest is not canonical")
    fields = {
        "abiVersion",
        "actionAuthorized",
        "algorithmId",
        "artifact",
        "compiler",
        "files",
        "fixedMemoryBytes",
        "headerSha256",
        "integrityOnlyNotAuthenticity",
        "opencvParity",
        "payloadDigest",
        "schemaVersion",
        "signed",
        "solverReadiness",
        "sourceSha256",
        "status",
    }
    manifest = _exact_fields(manifest, fields, "experimental package manifest")
    expected = {
        "schemaVersion": 1,
        "artifact": "captcha-safe-experimental-wasm",
        "status": "EXPERIMENTAL_UNSIGNED",
        "signed": False,
        "integrityOnlyNotAuthenticity": True,
        "solverReadiness": "PENDING",
        "actionAuthorized": False,
        "opencvParity": False,
        "abiVersion": 1,
        "algorithmId": ALGORITHM_ID,
        "fixedMemoryBytes": 16_777_216,
    }
    for field, expected_value in expected.items():
        if type(manifest[field]) is not type(expected_value) or manifest[field] != expected_value:
            raise ExperimentalPackageError(f"experimental package {field} is invalid")
    if not _is_digest(manifest["sourceSha256"]) or not _is_digest(manifest["headerSha256"]):
        raise ExperimentalPackageError("experimental package source binding is invalid")
    compiler = _exact_fields(
        manifest["compiler"], {"kind", "linkerVersion", "sourceDateEpoch", "version"}, "compiler"
    )
    if (
        not isinstance(compiler["kind"], str)
        or not isinstance(compiler["version"], str)
        or not isinstance(compiler["linkerVersion"], str)
        or type(compiler["sourceDateEpoch"]) is not int
        or compiler["sourceDateEpoch"] != 0
    ):
        raise ExperimentalPackageError("experimental package compiler identity is invalid")
    records = manifest["files"]
    if not isinstance(records, list) or len(records) != 2:
        raise ExperimentalPackageError("experimental package file records are invalid")
    expected_paths = [LOADER_NAME, WASM_NAME]
    for record, expected_path in zip(records, expected_paths, strict=True):
        record = _exact_fields(record, {"path", "sha256", "size"}, "file record")
        data = entries[expected_path]
        if (
            record["path"] != expected_path
            or not _is_digest(record["sha256"])
            or record["sha256"] != _digest(data)
            or type(record["size"]) is not int
            or record["size"] != len(data)
        ):
            raise ExperimentalPackageError("experimental package file record does not match")
    if manifest["payloadDigest"] != _digest(_canonical(records)):
        raise ExperimentalPackageError("experimental package payload digest does not match")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--wasm", type=Path, required=True)
    build.add_argument("--metadata", type=Path, required=True)
    build.add_argument("--loader", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--package", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            digest = build_package(args.wasm, args.metadata, args.loader, args.output)
            print(
                json.dumps(
                    {
                        "actionAuthorized": False,
                        "output": str(args.output),
                        "sha256": digest,
                        "signed": False,
                        "solverReadiness": "PENDING",
                        "status": "EXPERIMENTAL_UNSIGNED",
                    },
                    sort_keys=True,
                )
            )
        else:
            manifest = verify_package(args.package)
            print(
                json.dumps(
                    {
                        "actionAuthorized": manifest["actionAuthorized"],
                        "package": str(args.package),
                        "signed": manifest["signed"],
                        "solverReadiness": manifest["solverReadiness"],
                        "status": manifest["status"],
                    },
                    sort_keys=True,
                )
            )
        return 0
    except (ExperimentalPackageError, OSError, ValueError) as exc:
        print(f"experimental WASM package failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
