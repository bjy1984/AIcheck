#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ed25519 签名的本地授权许可管理。

许可证是一个 JSON 信封，签名只覆盖 ``payload`` 的规范化 JSON：

.. code-block:: json

    {
      "version": 1,
      "algorithm": "Ed25519",
      "payload": {
        "license_id": "engagement-2026-001",
        "email": "operator@example.com",
        "purpose": "authorized security exercise",
        "issued_at": "2026-07-19T00:00:00Z",
        "not_before": "2026-07-19T00:00:00Z",
        "expires_at": "2026-07-20T00:00:00Z",
        "allowed_hosts": ["captcha.example.com", "*.lab.example.com"],
        "allowed_scenes": ["scene-a"]
      },
      "signature": "base64url-ed25519-signature"
    }

公钥不是秘密。默认从 ``CAPTCHA_LICENSE_PUBLIC_KEY``（PEM 或 base64url
原始公钥）或 ``CAPTCHA_LICENSE_PUBLIC_KEY_FILE`` 加载，也可在构造函数中注入。
模块中不包含任何可用于签发许可证的私钥或共享密钥。
"""

import argparse
import base64
import binascii
import ipaddress
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, IO, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urlsplit

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # pragma: no cover - 由缺少依赖的测试覆盖行为，而非导入分支
    InvalidSignature = None  # type: ignore[assignment]
    serialization = None  # type: ignore[assignment]
    Ed25519PublicKey = None  # type: ignore[assignment,misc]


JsonObject = Dict[str, Any]
PublicKeyInput = Union[str, bytes, "Ed25519PublicKey"]
ActivationSource = Union[str, os.PathLike, IO[str], IO[bytes], Mapping[str, Any], bytes]


class LicenseFormatError(ValueError):
    """许可证内容或配置格式无效。"""


def _reject_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise LicenseFormatError("JSON 包含重复字段: %s" % key)
        result[key] = value
    return result


class LicenseManager:
    """验证、安装和展示签名许可证。

    ``verify_license`` 保留原来的 ``(valid, error)`` 返回语义，并增加可选的
    ``host``/``scene_id`` 范围检查。调用实际受控能力时应始终传入这两个值。
    """

    LICENSE_FILE = Path.home() / ".aliyun_captcha_license.json"
    LICENSE_FILE_ENV = "CAPTCHA_LICENSE_FILE"
    PUBLIC_KEY_ENV = "CAPTCHA_LICENSE_PUBLIC_KEY"
    PUBLIC_KEY_FILE_ENV = "CAPTCHA_LICENSE_PUBLIC_KEY_FILE"

    FORMAT_VERSION = 1
    ALGORITHM = "Ed25519"
    MAX_LICENSE_BYTES = 256 * 1024
    MAX_SCOPE_ITEMS = 128
    _ENVELOPE_FIELDS = frozenset(("version", "algorithm", "payload", "signature"))
    _PAYLOAD_FIELDS = frozenset(
        (
            "license_id",
            "email",
            "purpose",
            "issued_at",
            "not_before",
            "expires_at",
            "allowed_hosts",
            "allowed_scenes",
        )
    )
    _REQUIRED_PAYLOAD_FIELDS = _PAYLOAD_FIELDS - frozenset(("purpose",))
    _B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")
    _HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

    def __init__(
        self,
        public_key: Optional[PublicKeyInput] = None,
        public_key_file: Optional[Union[str, os.PathLike]] = None,
        license_file: Optional[Union[str, os.PathLike]] = None,
        now_provider: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if public_key is not None and public_key_file is not None:
            raise LicenseFormatError("public_key 与 public_key_file 只能提供一个")
        configured_file = license_file or os.environ.get(self.LICENSE_FILE_ENV)
        self.license_file = Path(configured_file) if configured_file else Path(self.LICENSE_FILE)
        self._public_key_input = public_key
        self._public_key_file_input = Path(public_key_file) if public_key_file is not None else None
        self._public_key = None
        self._public_key_error: Optional[str] = None
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._load_error: Optional[str] = None
        self._last_save_error: Optional[str] = None
        self.license_data = self._load_license()

    @staticmethod
    def canonicalize_payload(payload: Mapping[str, Any]) -> bytes:
        """返回签发端和验证端必须共同使用的规范化 payload 字节。"""
        if not isinstance(payload, Mapping):
            raise LicenseFormatError("payload 必须是 JSON 对象")
        try:
            encoded = json.dumps(
                dict(payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise LicenseFormatError("payload 不能规范化: %s" % exc) from exc
        return encoded.encode("utf-8")

    def _utc_now(self) -> datetime:
        now = self._now_provider()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise LicenseFormatError("当前时间提供器必须返回带时区的 datetime")
        return now.astimezone(timezone.utc)

    @classmethod
    def _parse_document(cls, raw: Union[str, bytes]) -> JsonObject:
        if isinstance(raw, bytes):
            if len(raw) > cls.MAX_LICENSE_BYTES:
                raise LicenseFormatError("许可证文件过大")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LicenseFormatError("许可证必须使用 UTF-8 编码") from exc
        elif isinstance(raw, str):
            if len(raw.encode("utf-8")) > cls.MAX_LICENSE_BYTES:
                raise LicenseFormatError("许可证文件过大")
            text = raw
        else:
            raise LicenseFormatError("许可证内容必须是文本或字节")

        def reject_constant(value: str) -> None:
            raise LicenseFormatError("JSON 不允许非有限数值: %s" % value)

        try:
            document = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=reject_constant,
            )
        except LicenseFormatError:
            raise
        except (json.JSONDecodeError, TypeError) as exc:
            raise LicenseFormatError("许可证不是有效 JSON: %s" % exc) from exc
        if not isinstance(document, dict):
            raise LicenseFormatError("许可证顶层必须是 JSON 对象")
        return document

    @staticmethod
    def _path_is_symlink(path: Path) -> bool:
        try:
            return stat.S_ISLNK(os.lstat(os.fspath(path)).st_mode)
        except FileNotFoundError:
            return False

    def _load_license(self) -> Optional[JsonObject]:
        path = self.license_file
        try:
            if self._path_is_symlink(path):
                raise LicenseFormatError("许可证文件不能是符号链接")

            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                fd = os.open(os.fspath(path), flags)
            except FileNotFoundError:
                return None

            with os.fdopen(fd, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise LicenseFormatError("许可证路径必须是普通文件")
                if info.st_mode & 0o077:
                    raise LicenseFormatError("许可证文件权限不安全，要求 0600")
                if info.st_size > self.MAX_LICENSE_BYTES:
                    raise LicenseFormatError("许可证文件过大")
                return self._parse_document(handle.read(self.MAX_LICENSE_BYTES + 1))
        except Exception as exc:
            self._load_error = str(exc)
            return None

    def _save_license(self, license_data: Mapping[str, Any]) -> bool:
        """以 0600 权限原子安装许可证，并且不跟随目标符号链接。"""
        path = self.license_file
        temporary_path: Optional[str] = None
        self._last_save_error = None
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self._path_is_symlink(path):
                raise LicenseFormatError("拒绝覆盖符号链接许可证文件")
            if path.exists() and not path.is_file():
                raise LicenseFormatError("许可证路径必须是普通文件")

            serialized = (
                json.dumps(
                    dict(license_data),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            if len(serialized) > self.MAX_LICENSE_BYTES:
                raise LicenseFormatError("许可证文件过大")

            fd, temporary_path = tempfile.mkstemp(
                prefix=".%s." % path.name,
                suffix=".tmp",
                dir=os.fspath(path.parent),
            )
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(serialized)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise

            # os.replace 替换的是链接目录项本身，不会写入链接目标；前置检查给出
            # 明确错误，replace 则保持写入的原子性。
            os.replace(temporary_path, os.fspath(path))
            temporary_path = None

            # 尽可能持久化目录项；不支持目录 fsync 的平台只影响断电耐久性。
            try:
                directory_fd = os.open(os.fspath(path.parent), os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
            return True
        except Exception as exc:
            self._last_save_error = str(exc)
            print("⚠️  许可证文件保存失败: %s" % exc)
            return False
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    @classmethod
    def _decode_base64url(cls, value: str, expected_length: int, label: str) -> bytes:
        if not isinstance(value, str) or not value or not cls._B64URL_RE.fullmatch(value):
            raise LicenseFormatError("%s 不是有效的 base64url" % label)
        if "=" in value[:-2] or len(value.rstrip("=")) % 4 == 1:
            raise LicenseFormatError("%s 不是有效的 base64url" % label)
        unpadded = value.rstrip("=")
        padded = unpadded + "=" * ((4 - len(unpadded) % 4) % 4)
        try:
            decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
        except (ValueError, binascii.Error) as exc:
            raise LicenseFormatError("%s 不是有效的 base64url" % label) from exc
        if len(decoded) != expected_length:
            raise LicenseFormatError("%s 长度错误" % label)
        return decoded

    def _public_key_material(self) -> PublicKeyInput:
        if self._public_key_input is not None:
            return self._public_key_input

        if self._public_key_file_input is not None:
            return self._read_public_key_file(self._public_key_file_input)

        inline = os.environ.get(self.PUBLIC_KEY_ENV)
        key_file = os.environ.get(self.PUBLIC_KEY_FILE_ENV)
        if inline and key_file:
            raise LicenseFormatError("公钥环境变量与公钥文件只能配置一个")
        if inline:
            return inline
        if key_file:
            return self._read_public_key_file(Path(key_file))
        raise LicenseFormatError(
            "未配置 Ed25519 公钥；请设置 %s 或 %s"
            % (self.PUBLIC_KEY_ENV, self.PUBLIC_KEY_FILE_ENV)
        )

    @classmethod
    def _read_public_key_file(cls, path: Path) -> bytes:
        """安全读取公钥信任锚，拒绝链接、非普通文件和可被他人写入的文件。"""
        try:
            if cls._path_is_symlink(path):
                raise LicenseFormatError("公钥文件不能是符号链接")
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(os.fspath(path), flags)
            with os.fdopen(fd, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise LicenseFormatError("公钥路径必须是普通文件")
                if info.st_mode & 0o022:
                    raise LicenseFormatError("公钥文件不能被 group/other 写入")
                data = handle.read(64 * 1024 + 1)
                if len(data) > 64 * 1024:
                    raise LicenseFormatError("公钥文件过大")
                return data
        except LicenseFormatError:
            raise
        except OSError as exc:
            raise LicenseFormatError("无法读取公钥文件: %s" % exc) from exc

    def _get_public_key(self) -> "Ed25519PublicKey":
        if self._public_key is not None:
            return self._public_key
        if self._public_key_error is not None:
            raise LicenseFormatError(self._public_key_error)
        if Ed25519PublicKey is None or serialization is None:
            self._public_key_error = "缺少 cryptography 依赖，无法验证 Ed25519 许可证"
            raise LicenseFormatError(self._public_key_error)

        try:
            material = self._public_key_material()
            if isinstance(material, Ed25519PublicKey):
                key = material
            else:
                raw = material.encode("utf-8") if isinstance(material, str) else bytes(material)
                # 原始公钥是任意 32 字节，首尾字节可能恰好属于 ASCII 空白；
                # 不能在判断 raw key 前调用 strip()。
                if not isinstance(material, str) and len(raw) == 32:
                    key = Ed25519PublicKey.from_public_bytes(raw)
                else:
                    stripped = raw.strip()
                    if stripped.startswith(b"-----BEGIN"):
                        loaded = serialization.load_pem_public_key(stripped)
                        if not isinstance(loaded, Ed25519PublicKey):
                            raise LicenseFormatError("公钥必须是 Ed25519 类型")
                        key = loaded
                    else:
                        try:
                            text = stripped.decode("ascii")
                        except UnicodeDecodeError as exc:
                            raise LicenseFormatError("Ed25519 公钥编码无效") from exc
                        decoded = self._decode_base64url(text, 32, "Ed25519 公钥")
                        key = Ed25519PublicKey.from_public_bytes(decoded)
            self._public_key = key
            return key
        except LicenseFormatError as exc:
            self._public_key_error = str(exc)
            raise
        except Exception as exc:
            self._public_key_error = "Ed25519 公钥加载失败: %s" % exc
            raise LicenseFormatError(self._public_key_error) from exc

    @staticmethod
    def _parse_timestamp(value: Any, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise LicenseFormatError("%s 必须是带时区的 ISO 8601 时间" % field)
        normalized = value.strip()
        if normalized.endswith(("Z", "z")):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise LicenseFormatError("%s 不是有效的 ISO 8601 时间" % field) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise LicenseFormatError("%s 必须包含 UTC 偏移，不能使用本地模糊时间" % field)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _normalize_policy_host(cls, host: Any) -> str:
        if not isinstance(host, str) or not host.strip():
            raise LicenseFormatError("allowed_hosts 必须包含非空主机名")
        value = host.strip().lower().rstrip(".")
        wildcard = value.startswith("*.")
        if wildcard:
            value = value[2:]
        if any(marker in value for marker in ("://", "/", "?", "#", "@")):
            raise LicenseFormatError("allowed_hosts 只能包含主机名，不能包含 URL 或凭据")
        if "*" in value:
            raise LicenseFormatError("主机通配符只能使用最左侧的 '*.'")
        normalized = cls._normalize_plain_host(value)
        try:
            ipaddress.ip_address(normalized)
        except ValueError:
            pass
        else:
            if wildcard:
                raise LicenseFormatError("IP 地址不能使用通配符")
        return "*." + normalized if wildcard else normalized

    @classmethod
    def _normalize_plain_host(cls, host: str) -> str:
        value = host.strip().lower().rstrip(".")
        if not value:
            raise LicenseFormatError("主机名不能为空")
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            pass
        try:
            ascii_host = value.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise LicenseFormatError("主机名 IDNA 编码无效") from exc
        if len(ascii_host) > 253:
            raise LicenseFormatError("主机名过长")
        if ascii_host == "localhost":
            return ascii_host
        labels = ascii_host.split(".")
        if len(labels) < 2 or any(not cls._HOST_LABEL_RE.fullmatch(label) for label in labels):
            raise LicenseFormatError("主机名格式无效: %s" % host)
        return ascii_host

    @classmethod
    def _normalize_target_host(cls, target: Any) -> str:
        if not isinstance(target, str) or not target.strip():
            raise LicenseFormatError("目标 host 不能为空")
        value = target.strip()
        try:
            if "://" in value:
                parsed = urlsplit(value)
                if parsed.scheme.lower() not in ("http", "https"):
                    raise LicenseFormatError("目标 URL 仅允许 http/https")
            else:
                parsed = urlsplit("//" + value)
            if parsed.username is not None or parsed.password is not None:
                raise LicenseFormatError("目标 host 不能包含凭据")
            if parsed.hostname is None:
                raise LicenseFormatError("目标 host 格式无效")
            # 访问 port 属性以触发非法端口的 ValueError。
            _ = parsed.port
            return cls._normalize_plain_host(parsed.hostname)
        except ValueError as exc:
            raise LicenseFormatError("目标 host 格式无效: %s" % exc) from exc

    @classmethod
    def _validate_payload_schema(cls, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise LicenseFormatError("payload 必须是 JSON 对象")
        keys = set(payload)
        missing = cls._REQUIRED_PAYLOAD_FIELDS - keys
        unknown = keys - cls._PAYLOAD_FIELDS
        if missing:
            raise LicenseFormatError("payload 缺少字段: %s" % ", ".join(sorted(missing)))
        if unknown:
            raise LicenseFormatError("payload 包含未知字段: %s" % ", ".join(sorted(unknown)))

        for field in ("license_id", "email"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise LicenseFormatError("%s 必须是合理长度的非空字符串" % field)
        purpose = payload.get("purpose")
        if purpose is not None and (not isinstance(purpose, str) or len(purpose) > 2048):
            raise LicenseFormatError("purpose 必须是字符串且不超过 2048 字符")

        hosts = payload.get("allowed_hosts")
        scenes = payload.get("allowed_scenes")
        if not isinstance(hosts, list) or not hosts or len(hosts) > cls.MAX_SCOPE_ITEMS:
            raise LicenseFormatError("allowed_hosts 必须是非空数组且范围合理")
        if not isinstance(scenes, list) or not scenes or len(scenes) > cls.MAX_SCOPE_ITEMS:
            raise LicenseFormatError("allowed_scenes 必须是非空数组且范围合理")

        normalized_hosts = [cls._normalize_policy_host(item) for item in hosts]
        if len(set(normalized_hosts)) != len(normalized_hosts):
            raise LicenseFormatError("allowed_hosts 包含重复主机范围")

        normalized_scenes = []
        for item in scenes:
            if not isinstance(item, str) or not item.strip() or len(item) > 512:
                raise LicenseFormatError("allowed_scenes 必须包含合理长度的非空字符串")
            if item == "*":
                raise LicenseFormatError("allowed_scenes 不允许无界通配符")
            normalized_scenes.append(item)
        if len(set(normalized_scenes)) != len(normalized_scenes):
            raise LicenseFormatError("allowed_scenes 包含重复 scene")

        result = dict(payload)
        result["_normalized_hosts"] = normalized_hosts
        result["_normalized_scenes"] = normalized_scenes
        return result

    @staticmethod
    def _host_allowed(host: str, policies: Sequence[str]) -> bool:
        for policy in policies:
            if policy.startswith("*."):
                suffix = policy[1:]  # 包含前导点，确保不匹配裸根域名。
                if host.endswith(suffix) and host != policy[2:]:
                    return True
            elif host == policy:
                return True
        return False

    def _validate_document(
        self,
        document: Any,
        hosts: Optional[Sequence[str]] = None,
        scene_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        try:
            if not isinstance(document, dict):
                raise LicenseFormatError("许可证顶层必须是 JSON 对象")
            fields = set(document)
            if fields != self._ENVELOPE_FIELDS:
                missing = self._ENVELOPE_FIELDS - fields
                unknown = fields - self._ENVELOPE_FIELDS
                details = []
                if missing:
                    details.append("缺少 %s" % ", ".join(sorted(missing)))
                if unknown:
                    details.append("未知 %s" % ", ".join(sorted(unknown)))
                raise LicenseFormatError("许可证信封字段错误（%s）" % "；".join(details))
            if type(document.get("version")) is not int or document["version"] != self.FORMAT_VERSION:
                raise LicenseFormatError("不支持的许可证版本")
            if document.get("algorithm") != self.ALGORITHM:
                raise LicenseFormatError("许可证算法必须是 Ed25519")
            payload = document.get("payload")
            if not isinstance(payload, dict):
                raise LicenseFormatError("payload 必须是 JSON 对象")
            signature = self._decode_base64url(document.get("signature"), 64, "signature")

            try:
                self._get_public_key().verify(signature, self.canonicalize_payload(payload))
            except Exception as exc:
                if InvalidSignature is not None and isinstance(exc, InvalidSignature):
                    return False, "许可证签名验证失败，内容可能已被篡改", None
                raise

            checked = self._validate_payload_schema(payload)
            issued_at = self._parse_timestamp(payload["issued_at"], "issued_at")
            not_before = self._parse_timestamp(payload["not_before"], "not_before")
            expires_at = self._parse_timestamp(payload["expires_at"], "expires_at")
            if issued_at > expires_at:
                raise LicenseFormatError("issued_at 不能晚于 expires_at")
            if not_before >= expires_at:
                raise LicenseFormatError("not_before 必须早于 expires_at")

            now = self._utc_now()
            if issued_at > now:
                return False, "许可证签发时间在未来", None
            if now < not_before:
                return False, "许可证尚未生效（生效时间: %s）" % payload["not_before"], None
            if now >= expires_at:
                return False, "许可证已过期（过期时间: %s）" % payload["expires_at"], None

            for required_host in hosts or ():
                normalized_target = self._normalize_target_host(required_host)
                if not self._host_allowed(normalized_target, checked["_normalized_hosts"]):
                    return False, "目标主机不在许可证授权范围内: %s" % normalized_target, None
            if scene_id is not None:
                if not isinstance(scene_id, str) or not scene_id:
                    return False, "scene_id 不能为空", None
                if scene_id not in checked["_normalized_scenes"]:
                    return False, "scene 不在许可证授权范围内: %s" % scene_id, None

            checked.pop("_normalized_hosts", None)
            checked.pop("_normalized_scenes", None)
            return True, None, checked
        except LicenseFormatError as exc:
            return False, str(exc), None
        except Exception as exc:
            return False, "许可证验证失败: %s" % exc, None

    def verify_license(
        self,
        host: Optional[str] = None,
        scene_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[bool, Optional[str]]:
        """验证签名、UTC 有效期及可选目标范围。

        为便于调用端迁移，``scene=...`` 可作为 ``scene_id`` 的别名。
        """
        scene_alias = kwargs.pop("scene", None)
        required_scene_id = kwargs.pop("required_scene_id", None)
        required_hosts = kwargs.pop("required_hosts", None)
        if kwargs:
            return False, "未知验证参数: %s" % ", ".join(sorted(kwargs))
        supplied_scenes = [item for item in (scene_id, scene_alias, required_scene_id) if item is not None]
        if len(supplied_scenes) > 1:
            return False, "scene、scene_id 与 required_scene_id 只能提供一个"
        if supplied_scenes:
            scene_id = supplied_scenes[0]

        hosts = []
        if host is not None:
            hosts.append(host)
        if required_hosts is not None:
            if isinstance(required_hosts, (str, bytes)) or not isinstance(required_hosts, Sequence):
                return False, "required_hosts 必须是主机名序列"
            if not required_hosts:
                return False, "required_hosts 不能为空"
            hosts.extend(required_hosts)
        if not all(isinstance(item, str) for item in hosts):
            return False, "待验证主机必须是字符串"

        if not self.license_data:
            if self._load_error:
                return False, "许可证文件读取失败: %s" % self._load_error
            return False, "未找到许可证文件，请先申请授权"

        valid, error, payload = self._validate_document(
            self.license_data,
            hosts=tuple(hosts),
            scene_id=scene_id,
        )
        if not valid:
            return False, error

        assert payload is not None
        expires_at = self._parse_timestamp(payload["expires_at"], "expires_at")
        seconds_left = max(0, int((expires_at - self._utc_now()).total_seconds()))
        days_left = seconds_left // 86400
        print("✅ 许可证验证通过")
        print("   许可证 ID: %s" % payload["license_id"])
        print("   授权邮箱: %s" % payload["email"])
        print("   使用目的: %s" % payload.get("purpose", "未说明"))
        print("   剩余天数: %s 天" % days_left)
        print("   过期时间: %s" % payload["expires_at"])
        return True, None

    def verify_scope(self, host: str, scene_id: str) -> Tuple[bool, Optional[str]]:
        """显式验证某个 host/scene 组合。"""
        return self.verify_license(host=host, scene_id=scene_id)

    def _read_activation_source(self, source: ActivationSource) -> JsonObject:
        if isinstance(source, Mapping):
            # 程序化调用可传对象；CLI 始终只接收文件路径或 stdin。
            return self._parse_document(
                json.dumps(dict(source), ensure_ascii=False, allow_nan=False)
            )
        if isinstance(source, bytes):
            return self._parse_document(source)
        if hasattr(source, "read"):
            content = source.read(self.MAX_LICENSE_BYTES + 1)  # type: ignore[union-attr]
            return self._parse_document(content)

        source_text = os.fspath(source)
        if source_text == "-":
            return self._parse_document(sys.stdin.read(self.MAX_LICENSE_BYTES + 1))
        path = Path(source_text)
        try:
            with path.open("rb") as handle:
                return self._parse_document(handle.read(self.MAX_LICENSE_BYTES + 1))
        except OSError as exc:
            raise LicenseFormatError("无法读取许可证源文件: %s" % exc) from exc

    def activate_license(self, source: ActivationSource = "-") -> bool:
        """从 JSON 文件或 stdin（``-``）验证并原子安装许可证。"""
        try:
            document = self._read_activation_source(source)
            valid, error, payload = self._validate_document(document)
            if not valid:
                print("❌ 许可证验证失败: %s" % error)
                return False
            if not self._save_license(document):
                print("❌ 许可证保存失败")
                return False

            self.license_data = dict(document)
            self._load_error = None
            assert payload is not None
            print("✅ 许可证激活成功！")
            print("   许可证 ID: %s" % payload["license_id"])
            print("   授权邮箱: %s" % payload["email"])
            print("   使用目的: %s" % payload.get("purpose", "未说明"))
            print("   过期时间: %s" % payload["expires_at"])
            return True
        except Exception as exc:
            print("❌ 许可证激活失败: %s" % exc)
            return False

    def show_license_info(self) -> bool:
        """显示已安装许可证中签名覆盖的信息。"""
        if not self.license_data:
            if self._load_error:
                print("❌ 许可证文件读取失败: %s" % self._load_error)
            else:
                print("❌ 未找到许可证")
            return False

        valid, error, payload = self._validate_document(self.license_data)
        if not valid or payload is None:
            print("❌ 许可证无效: %s" % error)
            return False

        print("\n" + "=" * 50)
        print("许可证信息")
        print("=" * 50)
        print("许可证 ID: %s" % payload["license_id"])
        print("授权邮箱: %s" % payload["email"])
        print("使用目的: %s" % payload.get("purpose", "未说明"))
        print("签发时间: %s" % payload["issued_at"])
        print("生效时间: %s" % payload["not_before"])
        print("过期时间: %s" % payload["expires_at"])
        print("授权主机: %s" % ", ".join(payload["allowed_hosts"]))
        print("授权场景: %s" % ", ".join(payload["allowed_scenes"]))
        print("=" * 50 + "\n")
        return True

    def require_license(
        self,
        host: Optional[str] = None,
        scene_id: Optional[str] = None,
    ) -> None:
        """验证失败时以非零状态退出。"""
        valid, error = self.verify_license(host=host, scene_id=scene_id)
        if not valid:
            print("\n" + "=" * 60)
            print("❌ 授权验证失败")
            print("=" * 60)
            print("错误信息: %s" % error)
            print("\n请从授权方获取签名许可证 JSON，然后运行：")
            print("  python3 license_manager.py activate /path/to/license.json")
            print("或通过标准输入安装（许可证不会进入 shell history）：")
            print("  python3 license_manager.py activate - < license.json")
            print("=" * 60 + "\n")
            raise SystemExit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ed25519 许可证管理工具")
    commands = parser.add_subparsers(dest="command")

    verify_parser = commands.add_parser("verify", help="验证已安装许可证")
    verify_parser.add_argument("--host", help="同时验证目标主机或 http(s) URL")
    verify_parser.add_argument("--scene", dest="scene_id", help="同时验证 scene ID")

    activate_parser = commands.add_parser("activate", help="从文件或 stdin 安装许可证")
    activate_parser.add_argument(
        "source",
        nargs="?",
        default="-",
        help="许可证 JSON 文件路径；使用 '-' 或省略表示从 stdin 读取",
    )

    commands.add_parser("info", help="查看并验证许可证信息")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行入口，返回可供自动化可靠判断的退出状态。"""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    manager = LicenseManager()
    if args.command == "verify":
        valid, error = manager.verify_license(host=args.host, scene_id=args.scene_id)
        if not valid:
            print("❌ %s" % error)
            return 1
        return 0
    if args.command == "activate":
        return 0 if manager.activate_license(args.source) else 1
    if args.command == "info":
        return 0 if manager.show_license_info() else 1
    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
