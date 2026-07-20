#!/usr/bin/env python3
"""Fail-closed release manifests and reproducible ZIP archives.

The release signature is intentionally detached from the payload manifest.  A
verifier must supply both a trusted Ed25519 public key and its expected SHA-256
fingerprint; shipping a public key inside the archive would not establish
trust because an attacker could replace the key, manifest, and signature.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

ARTIFACT_NAME = "captcha-safe"
SCHEMA_VERSION = 1
MANIFEST_NAME = "RELEASE-MANIFEST.json"
SIGNATURE_NAME = "RELEASE-MANIFEST.sig"
LOCK_NAME = "requirements.lock"
LOCK_METADATA_NAME = "requirements.lock.metadata.json"
SBOM_NAME = "SBOM.cdx.json"
HARNESS_MANIFEST_NAME = "harness-manifest.json"
ALLOWLIST_NAME = "scripts/release-files.txt"
HARNESS_BUILD_ID_RE = re.compile(r"^captcha-safe-[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]+$")
HARNESS_ASSET_CONTENT_TYPES = {
    "ai_studio_code (1).html": "text/html",
    "harness.css": "text/css",
    "harness.js": "text/javascript",
}
REQUIRED_PAYLOAD_NAMES = frozenset(
    {
        LOCK_NAME,
        LOCK_METADATA_NAME,
        SBOM_NAME,
        HARNESS_MANIFEST_NAME,
        ALLOWLIST_NAME,
    }
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_ENTRY_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FINGERPRINT_RE = re.compile(r"^SHA256:[0-9a-f]{64}$")
SIGNATURE_RE = re.compile(rb"^[A-Za-z0-9_-]{86}\n$")


class ReleaseIntegrityError(RuntimeError):
    """Raised when release input cannot be authenticated exactly."""


def _reject_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseIntegrityError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ReleaseIntegrityError(f"non-finite JSON number: {value}")


def parse_json_bytes(data: bytes, *, label: str, max_bytes: int = MAX_MANIFEST_BYTES) -> Any:
    if not isinstance(data, bytes) or not data or len(data) > max_bytes:
        raise ReleaseIntegrityError(f"{label} is empty or oversized")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseIntegrityError(f"{label} is not UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ReleaseIntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ReleaseIntegrityError(f"{label} is not valid JSON") from exc


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReleaseIntegrityError("value cannot be canonicalized as JSON") from exc


def validate_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024:
        raise ReleaseIntegrityError("release path is empty or oversized")
    if value != unicodedata.normalize("NFC", value):
        raise ReleaseIntegrityError(f"release path is not NFC-normalized: {value!r}")
    if "\\" in value or any(ord(character) < 0x20 for character in value):
        raise ReleaseIntegrityError(f"release path contains forbidden characters: {value!r}")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != value
        or value.startswith("/")
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ReleaseIntegrityError(f"release path is not canonical: {value!r}")
    return value


def _normalized_paths(paths: Iterable[str]) -> Tuple[str, ...]:
    normalized = tuple(validate_relative_path(path) for path in paths)
    if len(set(normalized)) != len(normalized):
        raise ReleaseIntegrityError("release path list contains duplicates")
    folded = [path.casefold() for path in normalized]
    if len(set(folded)) != len(folded):
        raise ReleaseIntegrityError("release paths collide on case-insensitive filesystems")
    return tuple(sorted(normalized))


def load_allowlist(path: Path) -> Tuple[str, ...]:
    data = _read_regular_file(path.parent, path.name, max_bytes=256 * 1024)
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ReleaseIntegrityError("release allowlist is not UTF-8") from exc
    entries = []
    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line != raw_line:
            raise ReleaseIntegrityError(f"allowlist line {number} has surrounding whitespace")
        entries.append(line)
    if not entries:
        raise ReleaseIntegrityError("release allowlist is empty")
    return _normalized_paths(entries)


def _path_components_are_safe(root: Path, relative_path: str) -> Path:
    validate_relative_path(relative_path)
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise ReleaseIntegrityError(f"cannot inspect release root: {root}") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise ReleaseIntegrityError("release root must be a real directory, not a symlink")
    current = root
    parts = PurePosixPath(relative_path).parts
    for part in parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise ReleaseIntegrityError(f"cannot inspect path component: {relative_path}") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ReleaseIntegrityError(
                f"release path traverses a non-directory or symlink: {relative_path}"
            )
    return root.joinpath(*parts)


def _read_regular_file(
    root: Path, relative_path: str, *, max_bytes: int = MAX_ENTRY_BYTES
) -> bytes:
    target = _path_components_are_safe(root, relative_path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(os.fspath(target), flags)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ReleaseIntegrityError(f"release entry is not a regular file: {relative_path}")
            if info.st_size < 0 or info.st_size > max_bytes:
                raise ReleaseIntegrityError(f"release entry is oversized: {relative_path}")
            data = handle.read(max_bytes + 1)
    except ReleaseIntegrityError:
        raise
    except OSError as exc:
        raise ReleaseIntegrityError(f"cannot read release entry: {relative_path}") from exc
    if len(data) > max_bytes:
        raise ReleaseIntegrityError(f"release entry is oversized: {relative_path}")
    return data


def inventory_source_tree(root: Path) -> Tuple[str, ...]:
    """Return every source file, ignoring only the VCS-owned ``.git`` tree."""

    root = Path(root)
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise ReleaseIntegrityError(f"cannot inspect source root: {root}") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise ReleaseIntegrityError("source root must be a real directory")

    found = []
    for directory, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        kept_directories = []
        for name in sorted(directory_names):
            child = directory_path / name
            relative = child.relative_to(root).as_posix()
            if relative == ".git":
                continue
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ReleaseIntegrityError(f"source tree contains a symlink: {relative}")
            if not stat.S_ISDIR(info.st_mode):
                raise ReleaseIntegrityError(
                    f"source tree contains a non-directory entry: {relative}"
                )
            kept_directories.append(name)
        directory_names[:] = kept_directories

        for name in sorted(file_names):
            child = directory_path / name
            relative = validate_relative_path(child.relative_to(root).as_posix())
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ReleaseIntegrityError(f"source tree contains a symlink: {relative}")
            if not stat.S_ISREG(info.st_mode):
                raise ReleaseIntegrityError(f"source tree contains a non-regular file: {relative}")
            found.append(relative)
    return _normalized_paths(found)


def assert_source_matches_allowlist(root: Path, allowlist: Sequence[str]) -> None:
    expected = set(_normalized_paths(allowlist))
    actual = set(inventory_source_tree(Path(root)))
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise ReleaseIntegrityError(
            "source tree does not match strict allowlist (" + "; ".join(details) + ")"
        )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_file_record(root: Path, relative_path: str) -> Dict[str, Any]:
    path = validate_relative_path(relative_path)
    data = _read_regular_file(Path(root), path)
    return {
        "mode": "0644",
        "path": path,
        "sha256": sha256_hex(data),
        "size": len(data),
    }


def read_release_file(root: Path, relative_path: str, *, max_bytes: int = MAX_ENTRY_BYTES) -> bytes:
    """Read one allowlisted payload without following symlinks."""

    return _read_regular_file(Path(root), relative_path, max_bytes=max_bytes)


def _extract_declared_harness_build_id(html_bytes: bytes, javascript_bytes: bytes) -> str:
    html_match = re.search(
        rb'<meta\s+name="captcha-safe-build-id"\s+content="([A-Za-z0-9._-]+)"\s*/?>',
        html_bytes,
    )
    javascript_match = re.search(
        rb'const\s+HARNESS_BUILD_ID\s*=\s*"([A-Za-z0-9._-]+)"\s*;',
        javascript_bytes,
    )
    if not html_match or not javascript_match:
        raise ReleaseIntegrityError("harness assets do not declare the required build ID")
    try:
        html_build_id = html_match.group(1).decode("ascii")
        javascript_build_id = javascript_match.group(1).decode("ascii")
    except UnicodeDecodeError as exc:
        raise ReleaseIntegrityError("harness build ID is not ASCII") from exc
    if html_build_id != javascript_build_id:
        raise ReleaseIntegrityError("HTML and JavaScript harness build IDs disagree")
    if not HARNESS_BUILD_ID_RE.fullmatch(html_build_id):
        raise ReleaseIntegrityError("harness build ID has an invalid format")
    return html_build_id


def create_harness_manifest(root: Path) -> Dict[str, Any]:
    root = Path(root)
    payloads = {
        name: _read_regular_file(root, name, max_bytes=4 * 1024 * 1024)
        for name in HARNESS_ASSET_CONTENT_TYPES
    }
    build_id = _extract_declared_harness_build_id(
        payloads["ai_studio_code (1).html"], payloads["harness.js"]
    )
    manifest = {
        "assets": {
            name: {
                "content_type": HARNESS_ASSET_CONTENT_TYPES[name],
                "sha256": sha256_hex(payloads[name]),
                "size": len(payloads[name]),
            }
            for name in sorted(payloads)
        },
        "build_id": build_id,
        "schema_version": 1,
    }
    validate_harness_manifest(manifest)
    return manifest


def validate_harness_manifest(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "assets",
        "build_id",
        "schema_version",
    }:
        raise ReleaseIntegrityError("harness manifest has unexpected top-level fields")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ReleaseIntegrityError("unsupported harness manifest version")
    build_id = value.get("build_id")
    if not isinstance(build_id, str) or not HARNESS_BUILD_ID_RE.fullmatch(build_id):
        raise ReleaseIntegrityError("harness manifest build_id is invalid")
    assets = value.get("assets")
    if not isinstance(assets, Mapping) or set(assets) != set(HARNESS_ASSET_CONTENT_TYPES):
        raise ReleaseIntegrityError("harness manifest must describe exactly HTML, JS, and CSS")
    for name in sorted(HARNESS_ASSET_CONTENT_TYPES):
        record = assets[name]
        if not isinstance(record, Mapping) or set(record) != {
            "content_type",
            "sha256",
            "size",
        }:
            raise ReleaseIntegrityError(f"harness asset record has unexpected fields: {name}")
        if record.get("content_type") != HARNESS_ASSET_CONTENT_TYPES[name]:
            raise ReleaseIntegrityError(f"harness asset content type is invalid: {name}")
        if not isinstance(record.get("sha256"), str) or not SHA256_RE.fullmatch(record["sha256"]):
            raise ReleaseIntegrityError(f"harness asset digest is invalid: {name}")
        if type(record.get("size")) is not int or not 0 <= record["size"] <= 4 * 1024 * 1024:
            raise ReleaseIntegrityError(f"harness asset size is invalid: {name}")
    return value


def encode_harness_manifest(value: Mapping[str, Any]) -> bytes:
    validate_harness_manifest(value)
    return canonical_json_bytes(value) + b"\n"


def parse_harness_manifest_bytes(data: bytes) -> Mapping[str, Any]:
    value = parse_json_bytes(data, label="harness manifest", max_bytes=64 * 1024)
    validate_harness_manifest(value)
    if data != canonical_json_bytes(value) + b"\n":
        raise ReleaseIntegrityError("harness manifest is not canonical JSON")
    return value


def verify_harness_assets(
    manifest: Mapping[str, Any],
    assets: Mapping[str, bytes],
    *,
    expected_build_id: str,
    content_types: Optional[Mapping[str, str]] = None,
) -> Mapping[str, Any]:
    validate_harness_manifest(manifest)
    if manifest["build_id"] != expected_build_id:
        raise ReleaseIntegrityError("harness manifest build ID does not match this release")
    if not isinstance(assets, Mapping) or set(assets) != set(HARNESS_ASSET_CONTENT_TYPES):
        raise ReleaseIntegrityError("harness payload must contain exactly HTML, JS, and CSS")
    if content_types is not None and set(content_types) != set(HARNESS_ASSET_CONTENT_TYPES):
        raise ReleaseIntegrityError(
            "harness content-type map must contain exactly HTML, JS, and CSS"
        )
    for name in sorted(HARNESS_ASSET_CONTENT_TYPES):
        data = assets[name]
        if not isinstance(data, bytes):
            raise ReleaseIntegrityError(f"harness asset must be bytes: {name}")
        record = manifest["assets"][name]
        if len(data) != record["size"] or sha256_hex(data) != record["sha256"]:
            raise ReleaseIntegrityError(f"harness asset digest mismatch: {name}")
        if content_types is not None and content_types[name] != record["content_type"]:
            raise ReleaseIntegrityError(f"harness asset content type mismatch: {name}")
    declared = _extract_declared_harness_build_id(
        assets["ai_studio_code (1).html"], assets["harness.js"]
    )
    if declared != expected_build_id:
        raise ReleaseIntegrityError("harness asset declarations do not match this release")
    return manifest


def verify_harness_manifest(
    root: Path,
    manifest_path: Optional[Path] = None,
    *,
    expected_build_id: Optional[str] = None,
) -> Mapping[str, Any]:
    root = Path(root)
    path = Path(manifest_path) if manifest_path is not None else root / HARNESS_MANIFEST_NAME
    try:
        relative_manifest = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ReleaseIntegrityError("harness manifest must be inside the project root") from exc
    manifest = parse_harness_manifest_bytes(
        _read_regular_file(root, relative_manifest, max_bytes=64 * 1024)
    )
    assets = {
        name: _read_regular_file(root, name, max_bytes=4 * 1024 * 1024)
        for name in HARNESS_ASSET_CONTENT_TYPES
    }
    return verify_harness_assets(
        manifest,
        assets,
        expected_build_id=expected_build_id or manifest["build_id"],
    )


def _load_crypto() -> Tuple[Any, Any, Any, Any]:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise ReleaseIntegrityError("cryptography is required for release signatures") from exc
    return serialization, Ed25519PrivateKey, Ed25519PublicKey, serialization.NoEncryption


def _decode_base64url_key(data: bytes, label: str) -> bytes:
    try:
        text = data.strip().decode("ascii")
    except UnicodeDecodeError as exc:
        raise ReleaseIntegrityError(f"{label} encoding is invalid") from exc
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", text):
        raise ReleaseIntegrityError(f"{label} is not base64url")
    unpadded = text.rstrip("=")
    if len(unpadded) % 4 == 1 or "=" in text[:-2]:
        raise ReleaseIntegrityError(f"{label} is not canonical base64url")
    try:
        decoded = base64.b64decode(
            unpadded + "=" * ((4 - len(unpadded) % 4) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise ReleaseIntegrityError(f"{label} is not base64url") from exc
    if len(decoded) != 32:
        raise ReleaseIntegrityError(f"{label} must decode to 32 bytes")
    return decoded


def load_private_key_bytes(data: bytes) -> Any:
    serialization, private_type, _, _ = _load_crypto()
    try:
        if data.lstrip().startswith(b"-----BEGIN"):
            key = serialization.load_pem_private_key(data, password=None)
        elif len(data) == 32:
            key = private_type.from_private_bytes(data)
        else:
            key = private_type.from_private_bytes(_decode_base64url_key(data, "private key"))
    except ReleaseIntegrityError:
        raise
    except Exception as exc:
        raise ReleaseIntegrityError("cannot load Ed25519 private key") from exc
    if not isinstance(key, private_type):
        raise ReleaseIntegrityError("release private key must be Ed25519")
    return key


def load_public_key_bytes(data: bytes) -> Any:
    serialization, _, public_type, _ = _load_crypto()
    try:
        if data.lstrip().startswith(b"-----BEGIN"):
            key = serialization.load_pem_public_key(data)
        elif len(data) == 32:
            key = public_type.from_public_bytes(data)
        else:
            key = public_type.from_public_bytes(_decode_base64url_key(data, "public key"))
    except ReleaseIntegrityError:
        raise
    except Exception as exc:
        raise ReleaseIntegrityError("cannot load Ed25519 public key") from exc
    if not isinstance(key, public_type):
        raise ReleaseIntegrityError("release public key must be Ed25519")
    return key


def read_key_file(path: Path, *, private: bool) -> bytes:
    path = Path(path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise ReleaseIntegrityError(f"cannot inspect key file: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ReleaseIntegrityError("key file must be a regular file, not a symlink")
    if private and info.st_mode & 0o077:
        raise ReleaseIntegrityError("private signing key permissions must be 0600 or stricter")
    return _read_regular_file(path.parent, path.name, max_bytes=64 * 1024)


def public_key_fingerprint(public_key: Any) -> str:
    serialization, _, public_type, _ = _load_crypto()
    if not isinstance(public_key, public_type):
        raise ReleaseIntegrityError("fingerprint input must be an Ed25519 public key")
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "SHA256:" + sha256_hex(raw)


def private_key_public_key(private_key: Any) -> Any:
    _, private_type, _, _ = _load_crypto()
    if not isinstance(private_key, private_type):
        raise ReleaseIntegrityError("signing input must be an Ed25519 private key")
    return private_key.public_key()


def create_release_manifest(
    root: Path,
    payload_paths: Sequence[str],
    *,
    version: str,
    source_date_epoch: int,
    signing_key_fingerprint: str,
) -> Dict[str, Any]:
    paths = _normalized_paths(payload_paths)
    if not REQUIRED_PAYLOAD_NAMES.issubset(paths):
        missing = sorted(REQUIRED_PAYLOAD_NAMES - set(paths))
        raise ReleaseIntegrityError(
            "release payload lacks required generated files: " + ",".join(missing)
        )
    if not VERSION_RE.fullmatch(version):
        raise ReleaseIntegrityError("release version has an invalid format")
    if type(source_date_epoch) is not int or source_date_epoch < 0:
        raise ReleaseIntegrityError("SOURCE_DATE_EPOCH must be a non-negative integer")
    if not FINGERPRINT_RE.fullmatch(signing_key_fingerprint):
        raise ReleaseIntegrityError("signing key fingerprint must be SHA256:<lowercase hex>")

    manifest = {
        "artifact": {
            "name": ARTIFACT_NAME,
            "sourceDateEpoch": source_date_epoch,
            "version": version,
        },
        "files": [make_file_record(Path(root), path) for path in paths],
        "schemaVersion": SCHEMA_VERSION,
        "signing": {
            "algorithm": "Ed25519",
            "publicKeyFingerprint": signing_key_fingerprint,
        },
    }
    validate_manifest(manifest)
    return manifest


def validate_manifest(value: Any) -> Tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Mapping) or set(value) != {
        "artifact",
        "files",
        "schemaVersion",
        "signing",
    }:
        raise ReleaseIntegrityError("release manifest has unexpected top-level fields")
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != SCHEMA_VERSION:
        raise ReleaseIntegrityError("unsupported release manifest version")

    artifact = value.get("artifact")
    if not isinstance(artifact, Mapping) or set(artifact) != {"name", "sourceDateEpoch", "version"}:
        raise ReleaseIntegrityError("release artifact metadata has unexpected fields")
    if artifact.get("name") != ARTIFACT_NAME or not isinstance(artifact.get("version"), str):
        raise ReleaseIntegrityError("release artifact identity is invalid")
    if not VERSION_RE.fullmatch(artifact["version"]):
        raise ReleaseIntegrityError("release version has an invalid format")
    if type(artifact.get("sourceDateEpoch")) is not int or artifact["sourceDateEpoch"] < 0:
        raise ReleaseIntegrityError("release SOURCE_DATE_EPOCH is invalid")

    signing = value.get("signing")
    if not isinstance(signing, Mapping) or set(signing) != {
        "algorithm",
        "publicKeyFingerprint",
    }:
        raise ReleaseIntegrityError("release signing metadata has unexpected fields")
    if signing.get("algorithm") != "Ed25519" or not isinstance(
        signing.get("publicKeyFingerprint"), str
    ):
        raise ReleaseIntegrityError("release signing metadata is invalid")
    if not FINGERPRINT_RE.fullmatch(signing["publicKeyFingerprint"]):
        raise ReleaseIntegrityError("release signing key fingerprint is invalid")

    files = value.get("files")
    if not isinstance(files, list) or not files or len(files) > 4096:
        raise ReleaseIntegrityError("release manifest file list is empty or oversized")
    records = []
    paths = []
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"mode", "path", "sha256", "size"}:
            raise ReleaseIntegrityError("release file record has unexpected fields")
        raw_path = item.get("path")
        if not isinstance(raw_path, str):
            raise ReleaseIntegrityError("release file record path must be text")
        path = validate_relative_path(raw_path)
        if item.get("mode") != "0644":
            raise ReleaseIntegrityError(f"release file mode is not canonical: {path}")
        if not isinstance(item.get("sha256"), str) or not SHA256_RE.fullmatch(item["sha256"]):
            raise ReleaseIntegrityError(f"release file digest is invalid: {path}")
        if type(item.get("size")) is not int or not 0 <= item["size"] <= MAX_ENTRY_BYTES:
            raise ReleaseIntegrityError(f"release file size is invalid: {path}")
        paths.append(path)
        records.append(item)
    normalized = _normalized_paths(paths)
    if tuple(paths) != normalized:
        raise ReleaseIntegrityError("release file records are not in canonical order")
    if not REQUIRED_PAYLOAD_NAMES.issubset(paths):
        raise ReleaseIntegrityError("release manifest lacks required generated payloads")
    if MANIFEST_NAME in paths or SIGNATURE_NAME in paths:
        raise ReleaseIntegrityError("manifest metadata files cannot describe themselves")
    if sum(record["size"] for record in records) > MAX_ARCHIVE_BYTES - MAX_MANIFEST_BYTES:
        raise ReleaseIntegrityError("release payload aggregate size exceeds the archive limit")
    return tuple(records)


def encode_manifest(manifest: Mapping[str, Any]) -> bytes:
    validate_manifest(manifest)
    return canonical_json_bytes(manifest) + b"\n"


def parse_manifest_bytes(data: bytes) -> Mapping[str, Any]:
    value = parse_json_bytes(data, label="release manifest")
    validate_manifest(value)
    canonical = canonical_json_bytes(value) + b"\n"
    if data != canonical:
        raise ReleaseIntegrityError("release manifest is not canonical JSON")
    return value


def sign_manifest_bytes(manifest_bytes: bytes, private_key: Any) -> bytes:
    parse_manifest_bytes(manifest_bytes)
    signature = private_key.sign(manifest_bytes)
    if len(signature) != 64:
        raise ReleaseIntegrityError("Ed25519 signer returned an invalid signature")
    return base64.urlsafe_b64encode(signature).rstrip(b"=") + b"\n"


def _decode_signature(signature_bytes: bytes) -> bytes:
    if not SIGNATURE_RE.fullmatch(signature_bytes):
        raise ReleaseIntegrityError("release signature is not canonical base64url")
    try:
        decoded = base64.urlsafe_b64decode(signature_bytes.strip() + b"==")
    except (ValueError, binascii.Error) as exc:
        raise ReleaseIntegrityError("release signature is invalid base64url") from exc
    if len(decoded) != 64:
        raise ReleaseIntegrityError("release signature has an invalid length")
    return decoded


def verify_manifest_signature(
    manifest_bytes: bytes,
    signature_bytes: bytes,
    public_key: Any,
    *,
    expected_fingerprint: str,
) -> Mapping[str, Any]:
    manifest = parse_manifest_bytes(manifest_bytes)
    if not FINGERPRINT_RE.fullmatch(expected_fingerprint):
        raise ReleaseIntegrityError("expected public-key fingerprint is invalid")
    actual_fingerprint = public_key_fingerprint(public_key)
    if actual_fingerprint != expected_fingerprint:
        raise ReleaseIntegrityError("trusted public key does not match the expected fingerprint")
    if manifest["signing"]["publicKeyFingerprint"] != expected_fingerprint:
        raise ReleaseIntegrityError("manifest signing fingerprint does not match the trusted key")
    signature = _decode_signature(signature_bytes)
    try:
        public_key.verify(signature, manifest_bytes)
    except Exception as exc:
        raise ReleaseIntegrityError("release manifest signature verification failed") from exc
    return manifest


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=validate_relative_path(path), date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.internal_attr = 0
    info.extra = b""
    info.comment = b""
    return info


def _write_canonical_zip(handle: Any, entries: Iterable[Tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(
        handle, mode="w", compression=zipfile.ZIP_STORED, allowZip64=False
    ) as archive:
        archive.comment = b""
        for path, data in entries:
            archive.writestr(_zip_info(path), data)


def _atomic_replace(path: Path, data_writer: Any, *, mode: int = 0o644) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise ReleaseIntegrityError(f"refusing to overwrite symlink: {path}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path: Optional[Path] = Path(temporary_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            data_writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary_path is None:
            raise ReleaseIntegrityError("atomic output temporary path was lost")
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def write_bytes_atomic(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    _atomic_replace(Path(path), lambda handle: handle.write(data), mode=mode)


def write_reproducible_zip(
    root: Path,
    payload_paths: Sequence[str],
    manifest_bytes: bytes,
    signature_bytes: bytes,
    output_path: Path,
) -> None:
    manifest = parse_manifest_bytes(manifest_bytes)
    records = validate_manifest(manifest)
    record_paths = tuple(record["path"] for record in records)
    paths = _normalized_paths(payload_paths)
    if paths != record_paths:
        raise ReleaseIntegrityError("ZIP payload paths do not match the signed manifest")
    _decode_signature(signature_bytes)

    entries = {path: _read_regular_file(Path(root), path) for path in paths}
    for record in records:
        data = entries[record["path"]]
        if len(data) != record["size"] or sha256_hex(data) != record["sha256"]:
            raise ReleaseIntegrityError(f"ZIP input differs from signed manifest: {record['path']}")
    entries[MANIFEST_NAME] = manifest_bytes
    entries[SIGNATURE_NAME] = signature_bytes

    def writer(handle: Any) -> None:
        _write_canonical_zip(handle, ((path, entries[path]) for path in sorted(entries)))

    _atomic_replace(Path(output_path), writer)


def _validate_zip_info(info: zipfile.ZipInfo) -> None:
    path = validate_relative_path(info.filename)
    if info.is_dir() or info.filename.endswith("/"):
        raise ReleaseIntegrityError(f"release ZIP contains a directory entry: {path}")
    if info.flag_bits != 0:
        raise ReleaseIntegrityError(f"release ZIP entry has non-canonical flags: {path}")
    if info.compress_type != zipfile.ZIP_STORED:
        raise ReleaseIntegrityError(f"release ZIP entry is not reproducibly stored: {path}")
    if info.date_time != FIXED_ZIP_TIME:
        raise ReleaseIntegrityError(f"release ZIP entry has a non-canonical timestamp: {path}")
    if info.extra or info.comment:
        raise ReleaseIntegrityError(f"release ZIP entry contains extra metadata: {path}")
    if info.create_system != 3 or info.internal_attr != 0:
        raise ReleaseIntegrityError(
            f"release ZIP entry has non-canonical platform metadata: {path}"
        )
    if info.external_attr != (stat.S_IFREG | 0o644) << 16:
        raise ReleaseIntegrityError(f"release ZIP entry mode is not regular 0644: {path}")
    if (
        info.file_size < 0
        or info.file_size > MAX_ENTRY_BYTES
        or info.compress_size != info.file_size
    ):
        raise ReleaseIntegrityError(f"release ZIP entry is oversized: {path}")


def _streams_match(first: Any, second: Any) -> bool:
    while True:
        first_chunk = first.read(1024 * 1024)
        second_chunk = second.read(1024 * 1024)
        if first_chunk != second_chunk:
            return False
        if not first_chunk:
            return True


def verify_release_archive(
    archive_path: Path,
    public_key: Any,
    *,
    expected_fingerprint: str,
) -> Mapping[str, Any]:
    archive_path = Path(archive_path)
    try:
        info = archive_path.lstat()
    except OSError as exc:
        raise ReleaseIntegrityError(f"cannot inspect release archive: {archive_path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ReleaseIntegrityError("release archive must be a regular file, not a symlink")
    if info.st_size <= 0 or info.st_size > MAX_ARCHIVE_BYTES:
        raise ReleaseIntegrityError("release archive is empty or oversized")

    try:
        with zipfile.ZipFile(archive_path, mode="r") as archive:
            if archive.comment:
                raise ReleaseIntegrityError("release ZIP has a non-empty archive comment")
            infos = archive.infolist()
            names = [entry.filename for entry in infos]
            if len(names) != len(set(names)):
                raise ReleaseIntegrityError("release ZIP contains duplicate paths")
            if tuple(names) != _normalized_paths(names):
                raise ReleaseIntegrityError("release ZIP entries are not in canonical order")
            for entry in infos:
                _validate_zip_info(entry)
            info_by_name = {entry.filename: entry for entry in infos}
            if MANIFEST_NAME not in info_by_name or SIGNATURE_NAME not in info_by_name:
                raise ReleaseIntegrityError("release ZIP lacks manifest metadata")
            manifest_bytes = archive.read(MANIFEST_NAME)
            signature_bytes = archive.read(SIGNATURE_NAME)
            manifest = verify_manifest_signature(
                manifest_bytes,
                signature_bytes,
                public_key,
                expected_fingerprint=expected_fingerprint,
            )
            records = validate_manifest(manifest)
            expected_names = {record["path"] for record in records} | {
                MANIFEST_NAME,
                SIGNATURE_NAME,
            }
            if set(names) != expected_names:
                extra = sorted(set(names) - expected_names)
                missing = sorted(expected_names - set(names))
                raise ReleaseIntegrityError(
                    f"release ZIP file set differs from manifest (missing={missing}; extra={extra})"
                )
            records_by_path = {record["path"]: record for record in records}
            with tempfile.TemporaryFile(mode="w+b") as canonical_archive:

                def canonical_entries() -> Iterable[Tuple[str, bytes]]:
                    for name in names:
                        data = archive.read(name)
                        record = records_by_path.get(name)
                        if record is not None and (
                            len(data) != record["size"] or sha256_hex(data) != record["sha256"]
                        ):
                            raise ReleaseIntegrityError(f"release payload digest mismatch: {name}")
                        yield name, data

                _write_canonical_zip(canonical_archive, canonical_entries())
                canonical_archive.seek(0)
                with archive_path.open("rb") as actual_archive:
                    if not _streams_match(actual_archive, canonical_archive):
                        raise ReleaseIntegrityError("release ZIP bytes are not canonical")
            return manifest
    except ReleaseIntegrityError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ReleaseIntegrityError("release archive cannot be read safely") from exc


def verify_release_directory(
    root: Path,
    public_key: Any,
    *,
    expected_fingerprint: str,
) -> Mapping[str, Any]:
    root = Path(root)
    manifest_bytes = _read_regular_file(root, MANIFEST_NAME, max_bytes=MAX_MANIFEST_BYTES)
    signature_bytes = _read_regular_file(root, SIGNATURE_NAME, max_bytes=1024)
    manifest = verify_manifest_signature(
        manifest_bytes,
        signature_bytes,
        public_key,
        expected_fingerprint=expected_fingerprint,
    )
    records = validate_manifest(manifest)
    expected = {record["path"] for record in records} | {MANIFEST_NAME, SIGNATURE_NAME}
    actual = set(inventory_source_tree(root))
    if actual != expected:
        raise ReleaseIntegrityError("release directory contains missing or extra files")
    for path in sorted(expected):
        target = _path_components_are_safe(root, path)
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o644:
            raise ReleaseIntegrityError(f"release directory entry mode is not regular 0644: {path}")
    for record in records:
        data = _read_regular_file(root, record["path"])
        if len(data) != record["size"] or sha256_hex(data) != record["sha256"]:
            raise ReleaseIntegrityError(f"release payload digest mismatch: {record['path']}")
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify signed captcha-safe release artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fingerprint = subparsers.add_parser(
        "fingerprint", help="print an Ed25519 public-key fingerprint"
    )
    fingerprint.add_argument("--public-key", required=True, type=Path)

    for name in ("verify-archive", "verify-directory"):
        child = subparsers.add_parser(name)
        child.add_argument("target", type=Path)
        child.add_argument("--public-key", required=True, type=Path)
        child.add_argument("--expected-fingerprint", required=True)
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        public_key = load_public_key_bytes(read_key_file(args.public_key, private=False))
        fingerprint = public_key_fingerprint(public_key)
        if args.command == "fingerprint":
            print(fingerprint)
            return 0
        if args.command == "verify-archive":
            manifest = verify_release_archive(
                args.target,
                public_key,
                expected_fingerprint=args.expected_fingerprint,
            )
        else:
            manifest = verify_release_directory(
                args.target,
                public_key,
                expected_fingerprint=args.expected_fingerprint,
            )
        print(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "status": "VERIFIED",
                    "version": manifest["artifact"]["version"],
                },
                sort_keys=True,
            )
        )
        return 0
    except ReleaseIntegrityError as exc:
        print(f"release verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
