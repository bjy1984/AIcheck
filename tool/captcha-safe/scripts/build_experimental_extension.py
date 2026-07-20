#!/usr/bin/env python3
"""Validate and reproducibly package the browser-only MV3 OpenCV extension.

This is deliberately not the signed Python release path.  The generated ZIP
is an integrity snapshot for review and unpacked installation only; it does
not turn a development installation into a trusted Chrome distribution.
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
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

sys.dont_write_bytecode = True
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from release_manifest import (  # noqa: E402
    ReleaseIntegrityError,
    canonical_json_bytes,
    validate_relative_path,
)

BUILD_MANIFEST_NAME = "EXPERIMENTAL-BUILD-MANIFEST.json"
BUILD_STATUS = "OPENCV_CNSE_SITE"
SOLVER_ALGORITHM = "opencv-edge-template-v1"
OPENCV_VERSION = "4.13.0"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MAX_CONFIG_BYTES = 256 * 1024
MAX_ENTRY_BYTES = 32 * 1024 * 1024
MAX_PACKAGE_BYTES = 160 * 1024 * 1024
MAX_PACKAGE_FILES = 2048
MAX_COMPRESSION_RATIO = 200
MIN_RATIO_CHECK_BYTES = 4096
EXPECTED_CSP = "script-src 'self' 'wasm-unsafe-eval'; object-src 'self';"
MINIMUM_CHROME_VERSION = 120
REQUIRED_PERMISSIONS = frozenset(
    ("offscreen", "scripting", "tabs")
)
EXPECTED_MANIFEST_FIELDS = frozenset(
    (
        "action",
        "background",
        "content_security_policy",
        "description",
        "incognito",
        "key",
        "manifest_version",
        "minimum_chrome_version",
        "name",
        "permissions",
        "host_permissions",
        "version",
    )
)
BUILD_CONFIG_FIELDS = frozenset(
    (
        "schemaVersion",
        "status",
        "extensionId",
        "minimumChromeVersion",
        "solveEnabled",
        "algorithm",
        "opencvVersion",
        "externalTargetsAllowed",
        "remoteCodeAllowed",
    )
)
OPENCV_ARTIFACT_PATH = "vendor/opencv/opencv.js"
OPENCV_LICENSE_PATH = "vendor/opencv/LICENSE"
OPENCV_README_PATH = "vendor/opencv/README.md"
OPENCV_SUMS_PATH = "vendor/opencv/SHA256SUMS"
OPENCV_LOCK_PATH = "vendor/opencv/lock.json"
OPENCV_VENDOR_PATHS = frozenset(
    (
        OPENCV_ARTIFACT_PATH,
        OPENCV_LICENSE_PATH,
        OPENCV_README_PATH,
        OPENCV_SUMS_PATH,
        OPENCV_LOCK_PATH,
    )
)
OPENCV_ARTIFACT_BYTES = 10_965_558
OPENCV_ARTIFACT_SHA256 = (
    "67b747b73392a012ad7af59adaef2bf1a1606a843ab75ece4ec19da981bd2138"
)
OPENCV_UPSTREAM_ARTIFACT_BYTES = 10_964_323
OPENCV_UPSTREAM_ARTIFACT_SHA256 = (
    "63366510248adf3a7eddf3e793dd825404efb7df3749f4d6f8557c7fa4ca8aa0"
)
OPENCV_LICENSE_SHA256 = (
    "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
)
OPENCV_LOCK_FIELDS = frozenset(
    (
        "schemaVersion",
        "name",
        "version",
        "releaseTag",
        "sourceUrl",
        "licenseSourceUrl",
        "artifactFile",
        "artifactBytes",
        "artifactSha256",
        "upstreamArtifactBytes",
        "upstreamArtifactSha256",
        "licenseFile",
        "licenseSha256",
        "distribution",
        "format",
        "embeddedWasm",
        "remoteCodeRequiredAtRuntime",
        "dynamicJavascriptExecution",
        "patchScript",
        "patchCount",
        "publishedEmscriptenVersion",
    )
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REMOTE_CODE_PATTERNS = (
    re.compile(r"\beval\s*\("),
    re.compile(r"\bnew\s+Function\s*\("),
    re.compile(r"\bFunction\s*\("),
    re.compile(r"\bimportScripts\s*\("),
    re.compile(r"\b(?:import|export)\s+[^;\n]*\bfrom\s*[\"']https?://"),
    re.compile(r"\bimport\s*(?:\(\s*)?[\"']https?://"),
    re.compile(r"<script\b[^>]*\bsrc\s*=\s*[\"']https?://", re.IGNORECASE),
    re.compile(r"@import\s+(?:url\s*\(\s*)?[\"']?https?://", re.IGNORECASE),
    re.compile(r"url\s*\(\s*[\"']?https?://", re.IGNORECASE),
    re.compile(r"(?:javascript\s*:|data\s*:\s*text/javascript)", re.IGNORECASE),
)
TEXT_SUFFIXES = frozenset(
    (".css", ".html", ".js", ".json", ".md", ".mjs", ".svg", ".txt")
)
RUNTIME_SUFFIXES = frozenset(
    (".css", ".html", ".js", ".json", ".md", ".mjs", ".png", ".svg", ".txt")
)
FORBIDDEN_PATH_PARTS = frozenset(
    (".git", ".idea", ".vscode", "drag-test", "node_modules", "tests", "wasm")
)
FORBIDDEN_RUNTIME_PATHS = frozenset(
    ("src/local-drag-self-test.js", "src/local-self-test.js")
)
PRODUCTION_RUNTIME_PATHS = frozenset(
    (
        "build-config.json",
        "manifest.json",
        "popup/popup.css",
        "popup/popup.html",
        "popup/popup.js",
        "release-files.txt",
        "solver/image-input.js",
        "solver/offscreen.html",
        "solver/offscreen.js",
        "solver/opencv-solver.js",
        "src/challenge-detector.js",
        "src/cnse-api-recognizer.js",
        "src/constants.js",
        "src/local-protocol.js",
        "src/service-worker.js",
        "src/solve-geometry.js",
        "src/solve-runner.js",
        *OPENCV_VENDOR_PATHS,
    )
)
PRIVATE_KEY_PATTERNS = (
    re.compile(
        rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
        re.IGNORECASE,
    ),
    re.compile(rb"-----BEGIN PGP PRIVATE KEY BLOCK-----", re.IGNORECASE),
)
EXTENSION_ID_RE = re.compile(r"^[a-p]{32}$")
CONSTANT_EXPORT_TEMPLATE = r"(?m)^export const {name} = ([^;\r\n]+);$"
EXPECTED_ZIP_EXTERNAL_ATTR = (stat.S_IFREG | 0o644) << 16
ALLOWED_ZIP_FLAG_BITS = frozenset((0, 0x800))


@dataclass(frozen=True)
class ExtensionIdentity:
    extension_id: str
    manifest_key_sha256: str


class ExtensionBuildError(ReleaseIntegrityError):
    """The experimental extension is unsafe, inconsistent, or malformed."""


def _reject_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ExtensionBuildError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ExtensionBuildError(f"non-finite JSON number: {value}")


def _parse_json(data: bytes, *, label: str) -> Any:
    if not data or len(data) > MAX_CONFIG_BYTES:
        raise ExtensionBuildError(f"{label} is empty or oversized")
    try:
        text = data.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ExtensionBuildError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ExtensionBuildError(f"{label} is not strict UTF-8 JSON") from exc


def _validated_path(value: Any) -> str:
    try:
        path = validate_relative_path(value)
    except ReleaseIntegrityError as exc:
        raise ExtensionBuildError(str(exc)) from exc
    if ":" in path:
        raise ExtensionBuildError(f"extension path contains a forbidden colon: {path!r}")
    return path


def _same_json_scalar(actual: Any, expected: object) -> bool:
    return type(actual) is type(expected) and actual == expected


def _der_element(data: bytes, offset: int, expected_tag: int) -> tuple[int, int]:
    if offset < 0 or offset + 2 > len(data) or data[offset] != expected_tag:
        raise ExtensionBuildError("manifest key is not a DER SubjectPublicKeyInfo value")
    first_length = data[offset + 1]
    if first_length < 0x80:
        content_start = offset + 2
        content_length = first_length
    else:
        length_octets = first_length & 0x7F
        if length_octets == 0 or length_octets > 4 or offset + 2 + length_octets > len(data):
            raise ExtensionBuildError("manifest key has an invalid DER length")
        encoded_length = data[offset + 2 : offset + 2 + length_octets]
        if encoded_length[0] == 0:
            raise ExtensionBuildError("manifest key has a non-canonical DER length")
        content_length = int.from_bytes(encoded_length, "big")
        if content_length < 0x80:
            raise ExtensionBuildError("manifest key has a non-canonical DER length")
        content_start = offset + 2 + length_octets
    content_end = content_start + content_length
    if content_end > len(data):
        raise ExtensionBuildError("manifest key has a truncated DER element")
    return content_start, content_end


def _decode_manifest_public_key(value: Any) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise ExtensionBuildError("manifest key must be a bounded canonical base64 string")
    try:
        encoded = value.encode("ascii")
        decoded = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise ExtensionBuildError("manifest key is not canonical base64") from exc
    if base64.b64encode(decoded) != encoded or not 64 <= len(decoded) <= 4096:
        raise ExtensionBuildError("manifest key is not a bounded canonical base64 public key")

    outer_start, outer_end = _der_element(decoded, 0, 0x30)
    if outer_end != len(decoded):
        raise ExtensionBuildError("manifest key has trailing DER data")
    algorithm_start, algorithm_end = _der_element(decoded, outer_start, 0x30)
    if algorithm_start >= algorithm_end or decoded[algorithm_start] != 0x06:
        raise ExtensionBuildError("manifest key has no public-key algorithm identifier")
    bit_string_start, bit_string_end = _der_element(decoded, algorithm_end, 0x03)
    if bit_string_end != outer_end or bit_string_start >= bit_string_end:
        raise ExtensionBuildError("manifest key is not a DER SubjectPublicKeyInfo value")
    if decoded[bit_string_start] != 0:
        raise ExtensionBuildError("manifest key has a non-canonical public-key bit string")
    return decoded


def _extension_identity(manifest: Mapping[str, Any]) -> ExtensionIdentity:
    public_key = _decode_manifest_public_key(manifest.get("key"))
    digest = hashlib.sha256(public_key).digest()
    extension_id = "".join(
        chr(ord("a") + nibble) for byte in digest[:16] for nibble in (byte >> 4, byte & 0x0F)
    )
    if not EXTENSION_ID_RE.fullmatch(extension_id):
        raise ExtensionBuildError("derived extension ID is invalid")
    return ExtensionIdentity(
        extension_id=extension_id,
        manifest_key_sha256=digest.hex(),
    )


def _read_regular(root: Path, relative: str, *, max_bytes: int = MAX_ENTRY_BYTES) -> bytes:
    relative = _validated_path(relative)
    current = root
    for part in PurePosixPath(relative).parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise ExtensionBuildError(f"cannot inspect extension path: {relative}") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ExtensionBuildError(f"extension path traverses a symlink: {relative}")
    target = root.joinpath(*PurePosixPath(relative).parts)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(os.fspath(target), flags)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ExtensionBuildError(f"extension entry is not a regular file: {relative}")
            if info.st_size < 0 or info.st_size > max_bytes:
                raise ExtensionBuildError(f"extension entry is oversized: {relative}")
            data = handle.read(max_bytes + 1)
    except ExtensionBuildError:
        raise
    except OSError as exc:
        raise ExtensionBuildError(f"cannot read extension entry: {relative}") from exc
    if len(data) > max_bytes:
        raise ExtensionBuildError(f"extension entry is oversized: {relative}")
    return data


def _parse_runtime_allowlist(data: bytes) -> tuple[str, ...]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ExtensionBuildError("extension release allowlist is not UTF-8") from exc
    entries: list[str] = []
    for line_number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line != raw:
            raise ExtensionBuildError(
                f"extension allowlist line {line_number} has surrounding whitespace"
            )
        normalized = _validated_path(line)
        candidate = PurePosixPath(normalized)
        if (
            any(part.startswith(".") or part in FORBIDDEN_PATH_PARTS for part in candidate.parts)
            or candidate.name in {"Thumbs.db", ".DS_Store"}
            or normalized in FORBIDDEN_RUNTIME_PATHS
            or (
                normalized not in OPENCV_VENDOR_PATHS
                and candidate.suffix.lower() not in RUNTIME_SUFFIXES
            )
        ):
            raise ExtensionBuildError(
                f"extension allowlist contains a forbidden runtime path: {normalized}"
            )
        entries.append(normalized)
    if "release-files.txt" not in entries:
        raise ExtensionBuildError("extension release allowlist must include itself")
    if BUILD_MANIFEST_NAME in entries:
        raise ExtensionBuildError("generated build manifest must not be in the source allowlist")
    if len(entries) != len(set(entries)):
        raise ExtensionBuildError("extension release allowlist contains duplicates")
    if len(entries) > MAX_PACKAGE_FILES:
        raise ExtensionBuildError("extension release allowlist contains too many files")
    folded = [entry.casefold() for entry in entries]
    if len(folded) != len(set(folded)):
        raise ExtensionBuildError("extension release paths collide case-insensitively")
    return tuple(sorted(entries))


def load_runtime_allowlist(extension_root: Path) -> tuple[str, ...]:
    data = _read_regular(extension_root, "release-files.txt", max_bytes=256 * 1024)
    return _parse_runtime_allowlist(data)


def _exact_object(value: Any, fields: frozenset[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ExtensionBuildError(f"{label} must be an object")
    missing = fields - set(value)
    unknown = set(value) - fields
    if missing or unknown:
        details = []
        if missing:
            details.append("missing=" + ",".join(sorted(missing)))
        if unknown:
            details.append("unknown=" + ",".join(sorted(unknown)))
        raise ExtensionBuildError(f"{label} schema mismatch ({'; '.join(details)})")
    return value


def _string_list(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ExtensionBuildError(f"manifest {field} must be a string array")
    if len(value) != len(set(value)):
        raise ExtensionBuildError(f"manifest {field} contains duplicates")
    return tuple(value)


def _manifest_resource(value: Any, *, label: str, paths: frozenset[str]) -> str:
    if not isinstance(value, str):
        raise ExtensionBuildError(f"manifest {label} must be a path")
    path = _validated_path(value)
    if path not in paths:
        raise ExtensionBuildError(f"manifest {label} is not allowlisted: {path}")
    return path


def _validate_manifest(value: Any, paths: frozenset[str]) -> ExtensionIdentity:
    if not isinstance(value, dict):
        raise ExtensionBuildError("extension manifest must be an object")
    if set(value) != EXPECTED_MANIFEST_FIELDS:
        raise ExtensionBuildError("extension manifest top-level schema is not exact")
    if not _same_json_scalar(value.get("manifest_version"), 3):
        raise ExtensionBuildError("extension must use Manifest V3")
    minimum = value.get("minimum_chrome_version")
    if minimum != str(MINIMUM_CHROME_VERSION):
        raise ExtensionBuildError(
            f"minimum_chrome_version must be exactly {MINIMUM_CHROME_VERSION}"
        )
    if value.get("incognito") != "split":
        raise ExtensionBuildError("extension must use split incognito mode")
    background = value.get("background")
    if not isinstance(background, dict) or set(background) != {"service_worker", "type"}:
        raise ExtensionBuildError("background worker schema is invalid")
    worker = background.get("service_worker")
    if background.get("type") != "module":
        raise ExtensionBuildError("background service worker must be an allowlisted module")
    _manifest_resource(worker, label="background.service_worker", paths=paths)
    content_security_policy = value.get("content_security_policy")
    if content_security_policy != {"extension_pages": EXPECTED_CSP}:
        raise ExtensionBuildError("extension CSP does not match the fixed no-eval policy")
    permissions = frozenset(_string_list(value.get("permissions"), field="permissions"))
    if permissions != REQUIRED_PERMISSIONS:
        raise ExtensionBuildError(
            "extension permissions do not match the CNSE-site runtime contract"
        )
    if value.get("host_permissions") != ["https://cnse.e-cqs.cn/*"]:
        raise ExtensionBuildError("extension host permissions must be limited to CNSE")

    for field, maximum in (("name", 128), ("description", 512)):
        text = value.get(field)
        if not isinstance(text, str) or not text or len(text.encode("utf-8")) > maximum:
            raise ExtensionBuildError(f"manifest {field} is invalid")
    version = value.get("version")
    if not isinstance(version, str) or not re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version
    ):
        raise ExtensionBuildError("manifest version must be canonical three-part semver")

    action = value.get("action")
    if not isinstance(action, dict) or set(action) != {"default_popup", "default_title"}:
        raise ExtensionBuildError("manifest action schema is invalid")
    _manifest_resource(action["default_popup"], label="action.default_popup", paths=paths)
    if not isinstance(action["default_title"], str) or not action["default_title"]:
        raise ExtensionBuildError("manifest action.default_title is invalid")

    return _extension_identity(value)


def _validate_build_config(value: Any, identity: ExtensionIdentity) -> Mapping[str, Any]:
    config = _exact_object(value, BUILD_CONFIG_FIELDS, label="build-config.json")
    expected = {
        "schemaVersion": 2,
        "status": BUILD_STATUS,
        "extensionId": identity.extension_id,
        "minimumChromeVersion": MINIMUM_CHROME_VERSION,
        "solveEnabled": True,
        "algorithm": SOLVER_ALGORITHM,
        "opencvVersion": OPENCV_VERSION,
        "externalTargetsAllowed": False,
        "remoteCodeAllowed": False,
    }
    if any(
        not _same_json_scalar(config[field], expected_value)
        for field, expected_value in expected.items()
    ):
        raise ExtensionBuildError(
            "CNSE-site build config does not match the runtime contract"
        )
    return config


def _parse_runtime_constant(data: bytes, name: str) -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtensionBuildError("src/constants.js is not UTF-8") from exc
    pattern = re.compile(CONSTANT_EXPORT_TEMPLATE.format(name=re.escape(name)))
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise ExtensionBuildError(f"runtime constant {name} must have exactly one literal export")
    try:
        return json.loads(matches[0], parse_constant=_reject_constant)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ExtensionBuildError(f"runtime constant {name} is not a JSON literal") from exc


def _validate_runtime_constants(
    data: bytes,
    config: Mapping[str, Any],
    identity: ExtensionIdentity,
) -> None:
    expected = {
        "BUILD_STATUS": config["status"],
        "EXPECTED_EXTENSION_ID": identity.extension_id,
        "MINIMUM_CHROME_VERSION": config["minimumChromeVersion"],
        "SOLVE_ENABLED": config["solveEnabled"],
        "SOLVER_ALGORITHM": config["algorithm"],
        "OPENCV_VERSION": config["opencvVersion"],
    }
    for name, expected_value in expected.items():
        actual = _parse_runtime_constant(data, name)
        if not _same_json_scalar(actual, expected_value):
            raise ExtensionBuildError(
                f"runtime constant {name} is inconsistent with the local build config"
            )


def _validate_text_file(path: str, data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtensionBuildError(f"runtime text file is not UTF-8: {path}") from exc
    for pattern in REMOTE_CODE_PATTERNS:
        if pattern.search(text):
            raise ExtensionBuildError(
                f"runtime file contains forbidden dynamic/remote code: {path}"
            )


def _validate_pinned_opencv(
    files: Mapping[str, bytes], config: Mapping[str, Any]
) -> None:
    if not OPENCV_VENDOR_PATHS <= set(files):
        raise ExtensionBuildError("extension package is missing the pinned OpenCV vendor set")

    artifact = files[OPENCV_ARTIFACT_PATH]
    license_data = files[OPENCV_LICENSE_PATH]
    artifact_digest = hashlib.sha256(artifact).hexdigest()
    license_digest = hashlib.sha256(license_data).hexdigest()
    if (
        len(artifact) != OPENCV_ARTIFACT_BYTES
        or artifact_digest != OPENCV_ARTIFACT_SHA256
        or license_digest != OPENCV_LICENSE_SHA256
    ):
        raise ExtensionBuildError("vendored OpenCV artifact does not match the fixed pin")

    lock = _exact_object(
        _parse_json(files[OPENCV_LOCK_PATH], label=OPENCV_LOCK_PATH),
        OPENCV_LOCK_FIELDS,
        label=OPENCV_LOCK_PATH,
    )
    expected_lock = {
        "schemaVersion": 1,
        "name": "OpenCV.js",
        "version": OPENCV_VERSION,
        "releaseTag": OPENCV_VERSION,
        "sourceUrl": f"https://docs.opencv.org/{OPENCV_VERSION}/opencv.js",
        "licenseSourceUrl": (
            f"https://raw.githubusercontent.com/opencv/opencv/{OPENCV_VERSION}/LICENSE"
        ),
        "artifactFile": "opencv.js",
        "artifactBytes": OPENCV_ARTIFACT_BYTES,
        "artifactSha256": OPENCV_ARTIFACT_SHA256,
        "upstreamArtifactBytes": OPENCV_UPSTREAM_ARTIFACT_BYTES,
        "upstreamArtifactSha256": OPENCV_UPSTREAM_ARTIFACT_SHA256,
        "licenseFile": "LICENSE",
        "licenseSha256": OPENCV_LICENSE_SHA256,
        "distribution": "official-versioned-documentation-build-with-mv3-csp-patch",
        "format": "single JavaScript file with embedded WebAssembly data URI",
        "embeddedWasm": True,
        "remoteCodeRequiredAtRuntime": False,
        "dynamicJavascriptExecution": False,
        "patchScript": "patch-mv3.mjs",
        "patchCount": 4,
        "publishedEmscriptenVersion": None,
    }
    if any(
        not _same_json_scalar(lock[field], expected)
        for field, expected in expected_lock.items()
    ):
        raise ExtensionBuildError("vendored OpenCV lock does not match the fixed pin")
    if config["opencvVersion"] != lock["version"]:
        raise ExtensionBuildError("OpenCV version is inconsistent with the build config")

    expected_sums = (
        f"{OPENCV_ARTIFACT_SHA256}  opencv.js\n"
        f"{OPENCV_LICENSE_SHA256}  LICENSE\n"
    ).encode("ascii")
    if files[OPENCV_SUMS_PATH] != expected_sums:
        raise ExtensionBuildError("vendored OpenCV checksum file is not canonical")


def _validate_runtime_files(
    paths: tuple[str, ...], files: Mapping[str, bytes]
) -> ExtensionIdentity:
    if not PRODUCTION_RUNTIME_PATHS <= set(paths):
        raise ExtensionBuildError("extension runtime allowlist is missing production files")
    if tuple(sorted(files)) != paths:
        raise ExtensionBuildError("extension runtime files do not match the sorted allowlist")
    if _parse_runtime_allowlist(files["release-files.txt"]) != paths:
        raise ExtensionBuildError("packaged release allowlist does not match runtime files")
    if sum(map(len, files.values())) > MAX_PACKAGE_BYTES:
        raise ExtensionBuildError("extension package is oversized")
    if any(pattern.search(data) for data in files.values() for pattern in PRIVATE_KEY_PATTERNS):
        raise ExtensionBuildError("extension package contains private-key material")
    manifest = _parse_json(files["manifest.json"], label="manifest.json")
    build_config = _parse_json(files["build-config.json"], label="build-config.json")
    identity = _validate_manifest(manifest, frozenset(paths))
    config = _validate_build_config(build_config, identity)
    _validate_runtime_constants(files["src/constants.js"], config, identity)
    _validate_pinned_opencv(files, config)
    for path, data in files.items():
        if PurePosixPath(path).suffix.lower() == ".json":
            _parse_json(data, label=path)
        if (
            path != OPENCV_ARTIFACT_PATH
            and PurePosixPath(path).suffix.lower() in TEXT_SUFFIXES
        ):
            _validate_text_file(path, data)
    return identity


def _validate_extension_source(
    extension_root: Path,
) -> tuple[tuple[str, ...], dict[str, bytes], ExtensionIdentity]:
    extension_root = Path(extension_root)
    try:
        root_info = extension_root.lstat()
    except OSError as exc:
        raise ExtensionBuildError(f"cannot inspect extension root: {extension_root}") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise ExtensionBuildError("extension root must be a real directory")
    paths = load_runtime_allowlist(extension_root)
    files = {path: _read_regular(extension_root, path) for path in paths}
    identity = _validate_runtime_files(paths, files)
    return paths, files, identity


def validate_extension_source(extension_root: Path) -> tuple[tuple[str, ...], dict[str, bytes]]:
    paths, files, _identity = _validate_extension_source(extension_root)
    return paths, files


def create_build_manifest(files: Mapping[str, bytes], identity: ExtensionIdentity) -> bytes:
    records = [
        {
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        for path, data in sorted(files.items())
    ]
    payload_digest = hashlib.sha256(canonical_json_bytes(records)).hexdigest()
    value = {
        "schemaVersion": 2,
        "artifact": "captcha-safe-opencv-cnse-site-extension",
        "status": BUILD_STATUS,
        "installType": "development",
        "extensionId": identity.extension_id,
        "manifestKeySha256": identity.manifest_key_sha256,
        "solveEnabled": True,
        "algorithm": SOLVER_ALGORITHM,
        "opencvVersion": OPENCV_VERSION,
        "externalTargetsAllowed": False,
        "remoteCodeAllowed": False,
        "payloadDigest": payload_digest,
        "integrityOnlyNotAuthenticity": True,
        "signed": False,
        "files": records,
    }
    return canonical_json_bytes(value) + b"\n"


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = EXPECTED_ZIP_EXTERNAL_ATTR
    return info


def build_experimental_extension(extension_root: Path, output_path: Path) -> str:
    paths, files, identity = _validate_extension_source(extension_root)
    build_manifest = create_build_manifest(files, identity)
    archive_names = (*paths, BUILD_MANIFEST_NAME)
    if len(archive_names) != len(set(archive_names)):
        raise ExtensionBuildError("extension archive plan contains duplicate entries")
    output_path = Path(output_path)
    resolved_root = Path(extension_root).resolve()
    resolved_output = output_path.resolve()
    if resolved_output == resolved_root or resolved_root in resolved_output.parents:
        raise ExtensionBuildError("extension output must be outside the source root")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", dir=output_path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as archive:
            for path in paths:
                archive.writestr(_zip_info(path), files[path])
            archive.writestr(_zip_info(BUILD_MANIFEST_NAME), build_manifest)
        verify_experimental_extension(temporary)
        os.replace(temporary, output_path)
        os.chmod(output_path, 0o644)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return hashlib.sha256(output_path.read_bytes()).hexdigest()


def verify_experimental_extension(archive_path: Path) -> Mapping[str, Any]:
    archive_path = Path(archive_path)
    try:
        info = archive_path.lstat()
    except OSError as exc:
        raise ExtensionBuildError(f"cannot inspect extension archive: {archive_path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ExtensionBuildError("extension archive must be a regular non-symlink file")
    if info.st_size <= 0 or info.st_size > MAX_PACKAGE_BYTES:
        raise ExtensionBuildError("extension archive is empty or oversized")
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ExtensionBuildError("extension archive contains duplicate entries")
            folded_names = [name.casefold() for name in names]
            if len(folded_names) != len(set(folded_names)):
                raise ExtensionBuildError("extension archive paths collide case-insensitively")
            if len(names) > MAX_PACKAGE_FILES + 1:
                raise ExtensionBuildError("extension archive contains too many entries")
            if BUILD_MANIFEST_NAME not in names:
                raise ExtensionBuildError("extension archive is missing its build manifest")
            if archive.comment:
                raise ExtensionBuildError("extension archive comment is forbidden")
            total_size = 0
            for entry in archive.infolist():
                _validated_path(entry.filename)
                expected_flags = 0 if entry.filename.isascii() else 0x800
                if (
                    entry.date_time != FIXED_ZIP_TIME
                    or entry.external_attr != EXPECTED_ZIP_EXTERNAL_ATTR
                    or entry.create_system != 3
                    or entry.create_version != 20
                    or entry.extract_version != 20
                    or entry.compress_type != zipfile.ZIP_DEFLATED
                    or entry.flag_bits not in ALLOWED_ZIP_FLAG_BITS
                    or entry.flag_bits != expected_flags
                    or entry.internal_attr != 0
                    or entry.volume != 0
                    or entry.extra
                    or entry.comment
                ):
                    raise ExtensionBuildError("extension archive metadata is not reproducible")
                if entry.file_size < 0 or entry.file_size > MAX_ENTRY_BYTES:
                    raise ExtensionBuildError("extension archive contains an oversized entry")
                if entry.compress_size < 0 or entry.compress_size > info.st_size:
                    raise ExtensionBuildError("extension archive has an invalid compressed size")
                if (
                    entry.file_size >= MIN_RATIO_CHECK_BYTES
                    and entry.file_size > max(1, entry.compress_size) * MAX_COMPRESSION_RATIO
                ):
                    raise ExtensionBuildError(
                        "extension archive contains a suspicious compression ratio"
                    )
                total_size += entry.file_size
            if total_size > MAX_PACKAGE_BYTES:
                raise ExtensionBuildError("extension archive expands beyond the package limit")
            build_manifest_data = archive.read(BUILD_MANIFEST_NAME)
            build_manifest = _parse_json(
                build_manifest_data,
                label=BUILD_MANIFEST_NAME,
            )
            if not isinstance(build_manifest, dict):
                raise ExtensionBuildError("experimental build manifest must be an object")
            if build_manifest_data != canonical_json_bytes(build_manifest) + b"\n":
                raise ExtensionBuildError("experimental build manifest is not canonical JSON")
            if set(build_manifest) != {
                "algorithm",
                "artifact",
                "externalTargetsAllowed",
                "extensionId",
                "files",
                "installType",
                "integrityOnlyNotAuthenticity",
                "manifestKeySha256",
                "opencvVersion",
                "payloadDigest",
                "remoteCodeAllowed",
                "schemaVersion",
                "signed",
                "solveEnabled",
                "status",
            }:
                raise ExtensionBuildError("experimental build manifest schema is invalid")
            if (
                not _same_json_scalar(build_manifest.get("schemaVersion"), 2)
                or build_manifest.get("artifact")
                != "captcha-safe-opencv-cnse-site-extension"
                or build_manifest.get("installType") != "development"
                or build_manifest.get("integrityOnlyNotAuthenticity") is not True
                or build_manifest.get("signed") is not False
                or build_manifest.get("solveEnabled") is not True
                or build_manifest.get("algorithm") != SOLVER_ALGORITHM
                or build_manifest.get("opencvVersion") != OPENCV_VERSION
                or build_manifest.get("externalTargetsAllowed") is not False
                or build_manifest.get("remoteCodeAllowed") is not False
                or not isinstance(build_manifest.get("extensionId"), str)
                or not EXTENSION_ID_RE.fullmatch(build_manifest["extensionId"])
                or not isinstance(build_manifest.get("manifestKeySha256"), str)
                or not SHA256_RE.fullmatch(build_manifest["manifestKeySha256"])
            ):
                raise ExtensionBuildError("experimental build manifest identity is invalid")
            records = build_manifest.get("files")
            if not isinstance(records, list):
                raise ExtensionBuildError("experimental build records must be an array")
            expected_names = {BUILD_MANIFEST_NAME}
            materialized: dict[str, bytes] = {}
            record_paths: list[str] = []
            for record in records:
                if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
                    raise ExtensionBuildError("experimental build record schema is invalid")
                path = _validated_path(record["path"])
                if path in materialized or path == BUILD_MANIFEST_NAME:
                    raise ExtensionBuildError("experimental build records contain duplicates")
                digest = record["sha256"]
                size = record["size"]
                if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                    raise ExtensionBuildError("experimental build record digest is invalid")
                if type(size) is not int or size < 0:
                    raise ExtensionBuildError("experimental build record size is invalid")
                try:
                    data = archive.read(path)
                except KeyError as exc:
                    raise ExtensionBuildError(
                        f"experimental build entry is missing: {path}"
                    ) from exc
                if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                    raise ExtensionBuildError(f"experimental build entry changed: {path}")
                materialized[path] = data
                record_paths.append(path)
                expected_names.add(path)
            if record_paths != sorted(record_paths):
                raise ExtensionBuildError("experimental build records are not sorted")
            if set(names) != expected_names:
                raise ExtensionBuildError("extension archive contains an unmanifested entry")
            if names != [*record_paths, BUILD_MANIFEST_NAME]:
                raise ExtensionBuildError("extension archive entry order is not deterministic")
            expected_digest = hashlib.sha256(canonical_json_bytes(records)).hexdigest()
            if build_manifest.get("payloadDigest") != expected_digest:
                raise ExtensionBuildError("experimental payload digest does not match")
            if build_manifest.get("status") != BUILD_STATUS:
                raise ExtensionBuildError("experimental build status is invalid")
            runtime_paths = tuple(record_paths)
            identity = _validate_runtime_files(runtime_paths, materialized)
            if build_manifest.get("extensionId") != identity.extension_id:
                raise ExtensionBuildError(
                    "experimental archive extension ID does not match the manifest key"
                )
            if build_manifest.get("manifestKeySha256") != identity.manifest_key_sha256:
                raise ExtensionBuildError("experimental archive manifest key digest does not match")
            return build_manifest
    except ExtensionBuildError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, KeyError, TypeError, ValueError) as exc:
        raise ExtensionBuildError("extension archive is invalid") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the browser-only OpenCV CNSE-site Chrome extension"
    )
    parser.add_argument("--extension-root", type=Path, default=Path("extension"))
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        digest = build_experimental_extension(args.extension_root, args.output)
        manifest = verify_experimental_extension(args.output)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "sha256": digest,
                    "status": BUILD_STATUS,
                    "extensionId": manifest["extensionId"],
                    "solveEnabled": True,
                    "algorithm": SOLVER_ALGORITHM,
                    "opencvVersion": OPENCV_VERSION,
                    "externalTargetsAllowed": False,
                    "remoteCodeAllowed": False,
                    "integrityOnlyNotAuthenticity": True,
                    "signed": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (ExtensionBuildError, OSError, ValueError) as exc:
        print(f"experimental extension build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
