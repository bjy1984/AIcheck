import base64
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:  # pragma: no cover - 测试环境可显式缺少可选运行依赖
    Ed25519PrivateKey = None
    serialization = None

from license_manager import LicenseManager


@unittest.skipIf(Ed25519PrivateKey is None, "cryptography 未安装")
class LicenseManagerTests(unittest.TestCase):
    NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.license_path = self.directory / "installed-license.json"
        self.private_key = Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()
        self.public_key_raw = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def payload(self, **overrides):
        payload = {
            "license_id": "engagement-001",
            "email": "operator@example.com",
            "purpose": "authorized exercise",
            "issued_at": "2026-07-19T00:00:00Z",
            "not_before": "2026-07-19T00:00:00+00:00",
            "expires_at": "2026-07-21T00:00:00+00:00",
            "allowed_hosts": ["captcha.example.com", "*.lab.example.com"],
            "allowed_scenes": ["scene-a", "scene-b"],
        }
        payload.update(overrides)
        return payload

    def document(self, payload=None):
        payload = payload or self.payload()
        signature = self.private_key.sign(LicenseManager.canonicalize_payload(payload))
        return {
            "version": 1,
            "algorithm": "Ed25519",
            "payload": payload,
            "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
        }

    def manager(self, path=None, public_key=None, now=None):
        return LicenseManager(
            public_key=self.public_key_raw if public_key is None else public_key,
            license_file=path or self.license_path,
            now_provider=lambda: now or self.NOW,
        )

    def install(self, document=None):
        document = document or self.document()
        manager = self.manager()
        with redirect_stdout(io.StringIO()):
            self.assertTrue(manager.activate_license(io.StringIO(json.dumps(document))))
        return manager

    def test_valid_signature_utc_and_scope(self):
        manager = self.install()

        with redirect_stdout(io.StringIO()):
            valid, error = manager.verify_license(
                host="https://captcha.example.com:443/widget", scene_id="scene-a"
            )
        self.assertTrue(valid, error)

        valid, error = manager.verify_license(
            host="asset.captcha.example.com", scene_id="scene-a"
        )
        self.assertFalse(valid)
        self.assertIn("主机", error)

        with redirect_stdout(io.StringIO()):
            valid, error = manager.verify_license(host="one.lab.example.com", scene="scene-b")
        self.assertTrue(valid, error)

        valid, error = manager.verify_license(host="lab.example.com", scene_id="scene-a")
        self.assertFalse(valid)
        self.assertIn("主机", error)

        valid, error = manager.verify_license(host="evil.example", scene_id="scene-a")
        self.assertFalse(valid)
        self.assertIn("主机", error)

        valid, error = manager.verify_license(
            host="captcha.example.com", scene_id="not-authorized"
        )
        self.assertFalse(valid)
        self.assertIn("scene", error)

    def test_runner_contract_supports_public_key_file_and_all_required_hosts(self):
        public_key_file = self.directory / "issuer-public-key.pem"
        public_key_file.write_bytes(
            self.public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        manager = LicenseManager(
            public_key_file=public_key_file,
            license_file=self.license_path,
            now_provider=lambda: self.NOW,
        )
        with redirect_stdout(io.StringIO()):
            self.assertTrue(manager.activate_license(io.StringIO(json.dumps(self.document()))))
            valid, error = manager.verify_license(
                required_scene_id="scene-a",
                required_hosts=("captcha.example.com", "asset.lab.example.com"),
            )
        self.assertTrue(valid, error)

        valid, error = manager.verify_license(
            required_scene_id="scene-a",
            required_hosts=("captcha.example.com", "not-authorized.example"),
        )
        self.assertFalse(valid)
        self.assertIn("not-authorized.example", error)

        valid, error = manager.verify_license(
            required_scene_id="scene-a",
            required_hosts=(),
        )
        self.assertFalse(valid)
        self.assertIn("不能为空", error)

    def test_payload_tampering_and_unsigned_envelope_fields_are_rejected(self):
        document = self.document()
        document["payload"]["email"] = "attacker@example.com"
        manager = self.manager()
        valid, error, _ = manager._validate_document(document)
        self.assertFalse(valid)
        self.assertIn("签名", error)

        document = self.document()
        document["activated_at"] = "2026-07-19T12:00:00Z"
        valid, error, _ = manager._validate_document(document)
        self.assertFalse(valid)
        self.assertIn("信封字段", error)

    def test_naive_future_and_expired_times_fail_closed(self):
        cases = (
            (self.payload(expires_at="2026-07-21T00:00:00"), "UTC 偏移"),
            (self.payload(not_before="2026-07-20T00:00:00Z"), "尚未生效"),
            (self.payload(expires_at="2026-07-19T12:00:00Z"), "已过期"),
            (self.payload(issued_at="2026-07-20T00:00:00Z"), "未来"),
        )
        manager = self.manager()
        for payload, expected in cases:
            with self.subTest(expected=expected):
                valid, error, _ = manager._validate_document(self.document(payload))
                self.assertFalse(valid)
                self.assertIn(expected, error)

    def test_activation_from_file_and_stdin_writes_atomic_0600_file(self):
        document = self.document()
        source = self.directory / "issued.json"
        source.write_text(json.dumps(document), encoding="utf-8")

        manager = self.manager()
        with redirect_stdout(io.StringIO()):
            self.assertTrue(manager.activate_license(source))
        self.assertEqual(stat.S_IMODE(self.license_path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(self.license_path.read_text("utf-8")), document)
        self.assertFalse(list(self.directory.glob(".installed-license.json.*.tmp")))

        second_path = self.directory / "stdin-license.json"
        second_manager = self.manager(path=second_path)
        with mock.patch("sys.stdin", io.StringIO(json.dumps(document))):
            with redirect_stdout(io.StringIO()):
                self.assertTrue(second_manager.activate_license("-"))
        self.assertEqual(stat.S_IMODE(second_path.stat().st_mode), 0o600)

        reloaded = self.manager()
        with redirect_stdout(io.StringIO()):
            valid, error = reloaded.verify_license(
                host="captcha.example.com", scene_id="scene-a"
            )
        self.assertTrue(valid, error)

    def test_failed_atomic_replace_preserves_existing_file_and_cleans_temp(self):
        original = b"existing-license-content\n"
        self.license_path.write_bytes(original)
        self.license_path.chmod(0o600)
        manager = self.manager()

        with mock.patch("license_manager.os.replace", side_effect=OSError("simulated failure")):
            with redirect_stdout(io.StringIO()):
                activated = manager.activate_license(io.StringIO(json.dumps(self.document())))
        self.assertFalse(activated)
        self.assertEqual(self.license_path.read_bytes(), original)
        self.assertFalse(list(self.directory.glob(".installed-license.json.*.tmp")))

    @unittest.skipUnless(hasattr(os, "symlink"), "平台不支持符号链接")
    def test_existing_symlink_is_neither_read_nor_overwritten(self):
        real_target = self.directory / "sensitive.txt"
        real_target.write_text("do-not-touch", encoding="utf-8")
        os.symlink(real_target, self.license_path)

        manager = self.manager()
        self.assertIsNone(manager.license_data)
        valid, error = manager.verify_license()
        self.assertFalse(valid)
        self.assertIn("符号链接", error)

        with redirect_stdout(io.StringIO()):
            self.assertFalse(manager.activate_license(io.StringIO(json.dumps(self.document()))))
        self.assertEqual(real_target.read_text("utf-8"), "do-not-touch")
        self.assertTrue(self.license_path.is_symlink())

    def test_duplicate_json_keys_and_insecure_installed_permissions_are_rejected(self):
        duplicate = '{"version":1,"version":1}'
        manager = self.manager()
        with redirect_stdout(io.StringIO()):
            self.assertFalse(manager.activate_license(io.StringIO(duplicate)))

        self.license_path.write_text(json.dumps(self.document()), encoding="utf-8")
        self.license_path.chmod(0o644)
        reloaded = self.manager()
        valid, error = reloaded.verify_license()
        self.assertFalse(valid)
        self.assertIn("0600", error)

    def test_public_key_can_be_base64url_and_missing_key_fails_cleanly(self):
        encoded = base64.urlsafe_b64encode(self.public_key_raw).rstrip(b"=").decode("ascii")
        manager = self.manager(public_key=encoded)
        valid, error, _ = manager._validate_document(self.document())
        self.assertTrue(valid, error)

        with mock.patch.dict(
            os.environ,
            {
                LicenseManager.PUBLIC_KEY_ENV: "",
                LicenseManager.PUBLIC_KEY_FILE_ENV: "",
            },
            clear=False,
        ):
            without_key = LicenseManager(
                license_file=self.license_path,
                now_provider=lambda: self.NOW,
            )
            valid, error, _ = without_key._validate_document(self.document())
        self.assertFalse(valid)
        self.assertIn("未配置", error)
        self.assertFalse(hasattr(LicenseManager, "SECRET_KEY"))

    @unittest.skipUnless(hasattr(os, "symlink"), "平台不支持符号链接")
    def test_public_key_trust_anchor_rejects_symlink(self):
        actual_key = self.directory / "actual-public-key"
        actual_key.write_bytes(self.public_key_raw)
        linked_key = self.directory / "linked-public-key"
        os.symlink(actual_key, linked_key)
        manager = LicenseManager(
            public_key_file=linked_key,
            license_file=self.license_path,
            now_provider=lambda: self.NOW,
        )
        valid, error, _ = manager._validate_document(self.document())
        self.assertFalse(valid)
        self.assertIn("符号链接", error)

    def test_cli_activate_verify_and_info_keep_basic_semantics(self):
        source = self.directory / "issued.json"
        source.write_text(json.dumps(self.document()), encoding="utf-8")
        script = Path(__file__).resolve().parents[1] / "license_manager.py"
        public_key = base64.urlsafe_b64encode(self.public_key_raw).rstrip(b"=").decode("ascii")
        environment = dict(os.environ)
        environment.update(
            {
                LicenseManager.PUBLIC_KEY_ENV: public_key,
                LicenseManager.LICENSE_FILE_ENV: str(self.license_path),
            }
        )

        activate = subprocess.run(
            [sys.executable, str(script), "activate", str(source)],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(activate.returncode, 0, activate.stdout + activate.stderr)

        verify = subprocess.run(
            [
                sys.executable,
                str(script),
                "verify",
                "--host",
                "captcha.example.com",
                "--scene",
                "scene-a",
            ],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertIn("许可证验证通过", verify.stdout)

        info = subprocess.run(
            [sys.executable, str(script), "info"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(info.returncode, 0, info.stdout + info.stderr)
        self.assertIn("授权主机", info.stdout)


if __name__ == "__main__":
    unittest.main()
