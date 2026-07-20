from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_experimental_extension import (
    BUILD_MANIFEST_NAME,
    FIXED_ZIP_TIME,
    ExtensionBuildError,
    build_experimental_extension,
    main,
    validate_extension_source,
    verify_experimental_extension,
)


class ExperimentalExtensionBuildTests(unittest.TestCase):
    MANIFEST_KEY = (
        "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2fJCGfLqncMF1uCJM4o9N8ok"
        "8GhRDKcB8NshaOgWIXQRIr8DG/PlrzV/dKbH5yiCFI4HqwpIoKL8ycAvgCkkuMfWvdvUa"
        "jy0ONgYd6iozbhxJXlJY6qvjG+Bur3YBtc1Ftw+Tbnfp4NtVIyJIIVwTqvYZnR78QaUT"
        "aRH/qMHNq5QOdGz9CTBE5crBFF2JuR5F+eWd9FhHgZAdogKPpKK3XPzh6iKDYDUdfEFPi"
        "XR0ELFqVCvcbGSHx89SOoQzEpjMd5yKG1modd8ltzLxR1coiLLnT1j7Wo8AOP8ugGbSyz"
        "ncoCpPU3CxeLelE+cfWTLmhWWhT4vyutRHBhX1M8WkwIDAQAB"
    )
    EXTENSION_ID = "bllipfmjmddgmgaabfmfhlkgbdhdiepe"
    MANIFEST_KEY_SHA256 = "1bb8f5c9c336c60015c57ba6137384f46843cd62358fe76237d71c82e2dbce46"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "extension"
        self.output = self.base / "extension.zip"
        self._write_fixture()

    @staticmethod
    def build_config() -> dict[str, object]:
        return {
            "schemaVersion": 2,
            "status": "OPENCV_CNSE_SITE",
            "extensionId": ExperimentalExtensionBuildTests.EXTENSION_ID,
            "minimumChromeVersion": 120,
            "solveEnabled": True,
            "algorithm": "opencv-edge-template-v1",
            "opencvVersion": "4.13.0",
            "externalTargetsAllowed": False,
            "remoteCodeAllowed": False,
        }

    @staticmethod
    def manifest() -> dict[str, object]:
        return {
            "manifest_version": 3,
            "name": "fixture",
            "description": "fixture experimental extension",
            "version": "0.1.0",
            "key": ExperimentalExtensionBuildTests.MANIFEST_KEY,
            "minimum_chrome_version": "120",
            "incognito": "split",
            "background": {
                "service_worker": "src/service-worker.js",
                "type": "module",
            },
            "permissions": ["offscreen", "scripting", "tabs"],
            "host_permissions": ["https://cnse.e-cqs.cn/*"],
            "action": {
                "default_popup": "popup/popup.html",
                "default_title": "fixture",
            },
            "content_security_policy": {
                "extension_pages": (
                    "script-src 'self' 'wasm-unsafe-eval'; object-src 'self';"
                )
            },
        }

    def _write_json(self, relative: str, value: object) -> None:
        (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
        (self.root / relative).write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def _write_fixture(self) -> None:
        self._write_json("manifest.json", self.manifest())
        self._write_json("build-config.json", self.build_config())
        text_files = (
            "popup/popup.css",
            "popup/popup.html",
            "popup/popup.js",
            "solver/image-input.js",
            "solver/offscreen.html",
            "solver/offscreen.js",
            "solver/opencv-solver.js",
            "src/challenge-detector.js",
            "src/cnse-api-recognizer.js",
            "src/local-protocol.js",
            "src/service-worker.js",
            "src/solve-geometry.js",
            "src/solve-runner.js",
        )
        for relative in text_files:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                "<!doctype html>\n" if relative.endswith(".html") else "export {};\n",
                encoding="utf-8",
            )
        (self.root / "src" / "constants.js").write_text(
            "\n".join(
                (
                    'export const BUILD_STATUS = "OPENCV_CNSE_SITE";',
                    f'export const EXPECTED_EXTENSION_ID = "{self.EXTENSION_ID}";',
                    "export const MINIMUM_CHROME_VERSION = 120;",
                    "export const SOLVE_ENABLED = true;",
                    'export const SOLVER_ALGORITHM = "opencv-edge-template-v1";',
                    'export const OPENCV_VERSION = "4.13.0";',
                    "",
                )
            ),
            encoding="utf-8",
        )
        vendor_source = Path(__file__).resolve().parents[1] / "extension" / "vendor" / "opencv"
        vendor_target = self.root / "vendor" / "opencv"
        vendor_target.mkdir(parents=True)
        for name in ("LICENSE", "README.md", "SHA256SUMS", "lock.json", "opencv.js"):
            shutil.copyfile(vendor_source / name, vendor_target / name)
        entries = (
            "build-config.json",
            "manifest.json",
            *text_files,
            "release-files.txt",
            "src/constants.js",
            "vendor/opencv/LICENSE",
            "vendor/opencv/README.md",
            "vendor/opencv/SHA256SUMS",
            "vendor/opencv/lock.json",
            "vendor/opencv/opencv.js",
        )
        (self.root / "release-files.txt").write_text(
            "\n".join(entries) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _canonical_json(value: object) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @staticmethod
    def _zip_info(name: str) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        return info

    def _rewrite_self_consistent_archive(self, output: Path, changes: dict[str, bytes]) -> None:
        build_experimental_extension(self.root, self.output)
        with zipfile.ZipFile(self.output) as source:
            names = source.namelist()
            entries = {name: source.read(name) for name in names}
        entries.update(changes)
        build_manifest = json.loads(entries[BUILD_MANIFEST_NAME])
        for record in build_manifest["files"]:
            path = record["path"]
            if path in changes:
                record["size"] = len(entries[path])
                record["sha256"] = hashlib.sha256(entries[path]).hexdigest()
        build_manifest["payloadDigest"] = hashlib.sha256(
            self._canonical_json(build_manifest["files"])
        ).hexdigest()
        entries[BUILD_MANIFEST_NAME] = self._canonical_json(build_manifest) + b"\n"
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name in names:
                archive.writestr(self._zip_info(name), entries[name])

    def test_build_is_reproducible_and_self_verifying(self) -> None:
        first_digest = build_experimental_extension(self.root, self.output)
        second = self.base / "extension-second.zip"
        second_digest = build_experimental_extension(self.root, second)
        self.assertEqual(first_digest, second_digest)
        self.assertEqual(self.output.read_bytes(), second.read_bytes())

        manifest = verify_experimental_extension(self.output)
        self.assertEqual(manifest["status"], "OPENCV_CNSE_SITE")
        self.assertEqual(manifest["extensionId"], self.EXTENSION_ID)
        self.assertEqual(manifest["manifestKeySha256"], self.MANIFEST_KEY_SHA256)
        self.assertTrue(manifest["solveEnabled"])
        self.assertEqual(manifest["algorithm"], "opencv-edge-template-v1")
        self.assertEqual(manifest["opencvVersion"], "4.13.0")
        self.assertFalse(manifest["externalTargetsAllowed"])
        self.assertFalse(manifest["remoteCodeAllowed"])
        self.assertFalse(manifest["signed"])
        self.assertTrue(manifest["integrityOnlyNotAuthenticity"])
        with zipfile.ZipFile(self.output) as archive:
            self.assertIn(BUILD_MANIFEST_NAME, archive.namelist())
            self.assertNotIn(".DS_Store", archive.namelist())

    def test_solver_contract_expansion_or_disablement_is_rejected(self) -> None:
        for field, value in (
            ("solveEnabled", False),
            ("algorithm", "other"),
            ("opencvVersion", "4.12.0"),
            ("externalTargetsAllowed", True),
            ("remoteCodeAllowed", True),
            ("schemaVersion", 1),
        ):
            with self.subTest(field=field):
                config = self.build_config()
                config[field] = value
                self._write_json("build-config.json", config)
                with self.assertRaisesRegex(ExtensionBuildError, "runtime contract"):
                    validate_extension_source(self.root)
                self._write_json("build-config.json", self.build_config())

    def test_manifest_key_extension_id_and_runtime_constants_are_bound(self) -> None:
        config = self.build_config()
        config["extensionId"] = "a" * 32
        self._write_json("build-config.json", config)
        with self.assertRaisesRegex(ExtensionBuildError, "runtime contract"):
            validate_extension_source(self.root)
        self._write_json("build-config.json", self.build_config())

        constants = self.root / "src" / "constants.js"
        original_constants = constants.read_text(encoding="utf-8")
        constants.write_text(
            original_constants.replace(
                'export const BUILD_STATUS = "OPENCV_CNSE_SITE";',
                'export const BUILD_STATUS = "EXTERNAL_DIAGNOSTIC";',
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ExtensionBuildError, "BUILD_STATUS"):
            validate_extension_source(self.root)
        constants.write_text(original_constants, encoding="utf-8")

        changed_key = bytearray(base64.b64decode(self.MANIFEST_KEY, validate=True))
        changed_key[-1] ^= 1
        manifest = self.manifest()
        manifest["key"] = base64.b64encode(changed_key).decode("ascii")
        self._write_json("manifest.json", manifest)
        with self.assertRaisesRegex(ExtensionBuildError, "runtime contract"):
            validate_extension_source(self.root)

    def test_any_permission_or_manifest_surface_expansion_is_rejected(self) -> None:
        cases = (
            ("permissions", ["debugger", "cookies"]),
            ("permissions", []),
            ("optional_permissions", ["webRequest"]),
            ("optional_host_permissions", ["<all_urls>"]),
            ("host_permissions", ["*://*/*"]),
            ("externally_connectable", {"matches": ["https://example.invalid/*"]}),
            ("devtools_page", "src/popup.html"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                manifest = self.manifest()
                manifest[field] = value
                self._write_json("manifest.json", manifest)
                with self.assertRaises(ExtensionBuildError):
                    validate_extension_source(self.root)
                self._write_json("manifest.json", self.manifest())

    def test_remote_or_dynamic_code_is_rejected(self) -> None:
        cases = (
            "eval('x');\n",
            "new Function('return 1')();\n",
            "importScripts('local.js');\n",
            "import value from 'https://cdn.invalid/module.js';\n",
            "const style = 'url(https://cdn.invalid/code.css)';\n",
            "const payload = 'javascript:alert(1)';\n",
        )
        worker = self.root / "src" / "service-worker.js"
        for source in cases:
            with self.subTest(source=source):
                worker.write_text(source, encoding="utf-8")
                with self.assertRaisesRegex(ExtensionBuildError, "dynamic/remote"):
                    validate_extension_source(self.root)

    def test_opencv_artifact_lock_and_checksums_are_fixed(self) -> None:
        artifact = self.root / "vendor" / "opencv" / "opencv.js"
        original = artifact.read_bytes()
        artifact.write_bytes(original[:-1] + bytes((original[-1] ^ 1,)))
        with self.assertRaisesRegex(ExtensionBuildError, "fixed pin"):
            validate_extension_source(self.root)
        artifact.write_bytes(original)

        lock_path = self.root / "vendor" / "opencv" / "lock.json"
        lock = json.loads(lock_path.read_bytes())
        lock["remoteCodeRequiredAtRuntime"] = True
        self._write_json("vendor/opencv/lock.json", lock)
        with self.assertRaisesRegex(ExtensionBuildError, "lock does not match"):
            validate_extension_source(self.root)

    def test_production_runtime_is_required_and_legacy_surfaces_are_forbidden(self) -> None:
        allowlist = self.root / "release-files.txt"
        original = allowlist.read_text(encoding="utf-8")
        allowlist.write_text(
            original.replace("solver/offscreen.js\n", ""), encoding="utf-8"
        )
        with self.assertRaisesRegex(ExtensionBuildError, "missing production files"):
            validate_extension_source(self.root)
        for path in ("drag-test/index.html", "src/local-self-test.js", "wasm/solver.wasm"):
            with self.subTest(path=path):
                allowlist.write_text(original + path + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ExtensionBuildError, "forbidden runtime path"):
                    validate_extension_source(self.root)

    def test_duplicate_json_keys_and_symlink_entries_fail_closed(self) -> None:
        (self.root / "build-config.json").write_text(
            '{"schemaVersion":1,"schemaVersion":1}\n', encoding="utf-8"
        )
        with self.assertRaisesRegex(ExtensionBuildError, "duplicate JSON key"):
            validate_extension_source(self.root)
        self._write_json("build-config.json", self.build_config())

        worker = self.root / "src" / "service-worker.js"
        worker.unlink()
        worker.symlink_to(self.root / "manifest.json")
        with self.assertRaises(ExtensionBuildError):
            validate_extension_source(self.root)

    def test_forbidden_paths_and_private_keys_are_excluded(self) -> None:
        allowlist = self.root / "release-files.txt"
        original = allowlist.read_text(encoding="utf-8")
        for path in (".hidden.js", "tests/fixture.js", "secret.pem"):
            with self.subTest(path=path):
                allowlist.write_text(original + path + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ExtensionBuildError, "forbidden runtime path"):
                    validate_extension_source(self.root)
        allowlist.write_text(original, encoding="utf-8")
        worker = self.root / "src" / "service-worker.js"
        for marker in (
            b"-----BEGIN PRIVATE KEY-----",
            b"-----BEGIN RSA PRIVATE KEY-----",
            b"-----BEGIN OPENSSH PRIVATE KEY-----",
            b"-----BEGIN PGP PRIVATE KEY BLOCK-----",
        ):
            with self.subTest(marker=marker):
                worker.write_bytes(b"// " + marker + b"\n")
                with self.assertRaisesRegex(ExtensionBuildError, "private-key material"):
                    validate_extension_source(self.root)

    def test_archive_with_unmanifested_file_is_rejected(self) -> None:
        build_experimental_extension(self.root, self.output)
        changed = self.base / "changed.zip"
        changed.write_bytes(self.output.read_bytes())
        with zipfile.ZipFile(changed, "a") as archive:
            archive.writestr("unexpected.txt", b"unexpected")
        with self.assertRaises(ExtensionBuildError):
            verify_experimental_extension(changed)

    def test_self_consistent_archive_tampering_is_revalidated(self) -> None:
        config = self.build_config()
        config["externalTargetsAllowed"] = True
        cases = (
            (
                "external-target-disabled",
                {"build-config.json": self._canonical_json(config) + b"\n"},
                "runtime contract",
            ),
            (
                "runtime-status-changed",
                {
                    "src/constants.js": (self.root / "src" / "constants.js")
                    .read_bytes()
                    .replace(
                        b'BUILD_STATUS = "OPENCV_CNSE_SITE"',
                        b'BUILD_STATUS = "EXTERNAL_DIAGNOSTIC"',
                    )
                },
                "BUILD_STATUS",
            ),
            (
                "remote-code",
                {"src/service-worker.js": b"globalThis.eval('unsafe');\n"},
                "dynamic/remote",
            ),
            (
                "private-key",
                {"src/service-worker.js": b"// -----BEGIN EC PRIVATE KEY-----\n"},
                "private-key material",
            ),
        )
        for name, changes, message in cases:
            with self.subTest(name=name):
                changed = self.base / f"{name}.zip"
                self._rewrite_self_consistent_archive(changed, changes)
                with self.assertRaisesRegex(ExtensionBuildError, message):
                    verify_experimental_extension(changed)

    def test_zip_bomb_and_nonportable_paths_are_rejected_before_extraction(self) -> None:
        bomb = self.base / "bomb.zip"
        with zipfile.ZipFile(
            bomb,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            archive.writestr(self._zip_info("payload.txt"), b"A" * (1024 * 1024))
            archive.writestr(self._zip_info(BUILD_MANIFEST_NAME), b"{}\n")
        with self.assertRaisesRegex(ExtensionBuildError, "compression ratio"):
            verify_experimental_extension(bomb)

        for name in ("../escape.js", "C:/escape.js"):
            with self.subTest(name=name):
                unsafe = self.base / (hashlib.sha256(name.encode()).hexdigest() + ".zip")
                with zipfile.ZipFile(
                    unsafe,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                ) as archive:
                    archive.writestr(self._zip_info(name), b"unsafe")
                    archive.writestr(self._zip_info(BUILD_MANIFEST_NAME), b"{}\n")
                with self.assertRaises(ExtensionBuildError):
                    verify_experimental_extension(unsafe)

        collision = self.base / "case-collision.zip"
        with zipfile.ZipFile(
            collision,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            archive.writestr(self._zip_info("src/a.js"), b"a")
            archive.writestr(self._zip_info("src/A.js"), b"A")
            archive.writestr(self._zip_info(BUILD_MANIFEST_NAME), b"{}\n")
        with self.assertRaisesRegex(ExtensionBuildError, "case-insensitively"):
            verify_experimental_extension(collision)

    def test_cli_reports_unsigned_identity_and_failures(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(
                [
                    "--extension-root",
                    str(self.root),
                    "--output",
                    str(self.output),
                ]
            )
        self.assertEqual(status, 0)
        self.assertEqual(stderr.getvalue(), "")
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["extensionId"], self.EXTENSION_ID)
        self.assertEqual(report["status"], "OPENCV_CNSE_SITE")
        self.assertTrue(report["solveEnabled"])
        self.assertEqual(report["algorithm"], "opencv-edge-template-v1")
        self.assertEqual(report["opencvVersion"], "4.13.0")
        self.assertFalse(report["externalTargetsAllowed"])
        self.assertFalse(report["remoteCodeAllowed"])
        self.assertFalse(report["signed"])
        self.assertTrue(report["integrityOnlyNotAuthenticity"])

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(
                [
                    "--extension-root",
                    str(self.base / "missing"),
                    "--output",
                    str(self.base / "missing.zip"),
                ]
            )
        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("build failed", stderr.getvalue())

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(
                [
                    "--extension-root",
                    str(self.root),
                    "--output",
                    str(self.root / "unsafe.zip"),
                ]
            )
        self.assertEqual(status, 1)
        self.assertFalse((self.root / "unsafe.zip").exists())
        self.assertIn("outside the source root", stderr.getvalue())

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([])

    def test_archive_metadata_and_noncanonical_build_manifest_are_rejected(self) -> None:
        build_experimental_extension(self.root, self.output)
        with zipfile.ZipFile(self.output) as source:
            entries = {name: source.read(name) for name in source.namelist()}

        bad_metadata = self.base / "bad-metadata.zip"
        with zipfile.ZipFile(bad_metadata, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        with self.assertRaisesRegex(ExtensionBuildError, "metadata"):
            verify_experimental_extension(bad_metadata)

        value = json.loads(entries[BUILD_MANIFEST_NAME])
        entries[BUILD_MANIFEST_NAME] = json.dumps(value, indent=2).encode("utf-8") + b"\n"
        noncanonical = self.base / "noncanonical.zip"
        with zipfile.ZipFile(
            noncanonical,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name, data in entries.items():
                info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (0o100000 | 0o644) << 16
                archive.writestr(info, data)
        with self.assertRaisesRegex(ExtensionBuildError, "not canonical JSON"):
            verify_experimental_extension(noncanonical)


if __name__ == "__main__":
    unittest.main()
