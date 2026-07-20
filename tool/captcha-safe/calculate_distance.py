#!/usr/bin/env python3
"""Download approved CAPTCHA images and calculate a validated match location.

The module intentionally contains no browser automation and never executes text
obtained from a web page.  It can therefore be used as a small, testable library
by the authorised browser runner.
"""

from __future__ import annotations

import argparse
import io
import ipaddress
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import SplitResult, urlsplit


DEFAULT_IMAGE_HOSTS = ("static-captcha.aliyuncs.com",)
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_PIXELS = 20_000_000
DEFAULT_MIN_CONFIDENCE = 0.50
ALLOWED_IMAGE_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})
HOST_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class CaptchaSafeError(RuntimeError):
    """Base class for errors that are safe to show to a CLI user."""


class PolicyError(CaptchaSafeError):
    """Raised when an input violates the network or resource policy."""


class DownloadError(CaptchaSafeError):
    """Raised when an approved image cannot be downloaded safely."""


class ImageValidationError(CaptchaSafeError):
    """Raised when bytes are not a supported, bounded image."""


class SolverError(CaptchaSafeError):
    """Raised when the matcher fails or returns an invalid structure."""


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    format: str
    byte_length: int


@dataclass(frozen=True)
class DistanceResult:
    """A ddddocr 1.6.1 match in original background-image pixels."""

    target_x: int
    target_y: int
    target: Tuple[int, int]
    confidence: float
    target_image: ImageInfo
    background_image: ImageInfo

    @property
    def match_center_x(self) -> int:
        """Return the desired puzzle center in original background pixels."""

        return self.target_x

    def to_dict(self) -> Mapping[str, Any]:
        value = asdict(self)
        value["coordinate_space"] = "background_image_center"
        value["match_center_x"] = self.match_center_x
        return value


@dataclass(frozen=True)
class DownloadPolicy:
    allowed_hosts: Tuple[str, ...] = DEFAULT_IMAGE_HOSTS
    max_bytes: int = DEFAULT_MAX_BYTES
    max_pixels: int = DEFAULT_MAX_PIXELS
    connect_timeout: float = 5.0
    read_timeout: float = 10.0

    def __post_init__(self) -> None:
        normalized = tuple(_normalize_host(host) for host in self.allowed_hosts)
        if not normalized:
            raise PolicyError("at least one approved image host is required")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (self.max_bytes, self.max_pixels)
        ):
            raise PolicyError("resource limits must be positive integers")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
            for value in (self.connect_timeout, self.read_timeout)
        ):
            raise PolicyError("network timeouts must be positive finite numbers")
        object.__setattr__(self, "allowed_hosts", normalized)

    def validate_url(self, value: str) -> SplitResult:
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise PolicyError("image URL is missing or too long")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise PolicyError("image URL contains control characters")

        try:
            parsed = urlsplit(value)
            username = parsed.username
            password = parsed.password
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise PolicyError("image URL is invalid") from exc
        if parsed.scheme.lower() != "https":
            raise PolicyError("only HTTPS image URLs are permitted")
        if username is not None or password is not None:
            raise PolicyError("credentials in image URLs are not permitted")
        if not hostname:
            raise PolicyError("image URL has no host")
        if parsed.fragment:
            raise PolicyError("image URL fragments are not permitted")
        if port not in (None, 443):
            raise PolicyError("only the default HTTPS port is permitted")

        host = _normalize_host(hostname)
        try:
            ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            pass
        else:
            raise PolicyError("IP-literal image hosts are not permitted")

        if host not in self.allowed_hosts:
            raise PolicyError(f"image host is outside the approved scope: {host}")
        return parsed


def _normalize_host(host: str) -> str:
    if not isinstance(host, str):
        raise PolicyError("approved host must be text")
    value = host.strip().rstrip(".").lower()
    if not value:
        raise PolicyError("approved host cannot be empty")
    try:
        normalized = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise PolicyError(f"invalid host name: {host!r}") from exc
    try:
        ipaddress.ip_address(normalized.strip("[]"))
    except ValueError:
        pass
    else:
        raise PolicyError("IP-literal hosts are not permitted")
    labels = normalized.split(".")
    if len(normalized) > 253 or len(labels) < 2 or any(
        not HOST_LABEL_PATTERN.fullmatch(label) for label in labels
    ):
        raise PolicyError(f"invalid or overly broad host name: {host!r}")
    return normalized


def _validate_image_bytes(data: bytes, policy: DownloadPolicy) -> ImageInfo:
    if not data:
        raise ImageValidationError("image response is empty")
    if len(data) > policy.max_bytes:
        raise ImageValidationError("image exceeds the configured byte limit")

    try:
        from PIL import Image
    except ImportError as exc:
        raise ImageValidationError("Pillow is required for image validation") from exc

    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = (image.format or "").upper()
            width, height = image.size
            image.verify()
    except Exception as exc:
        raise ImageValidationError("response is not a valid image") from exc

    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ImageValidationError(f"unsupported image format: {image_format or 'unknown'}")
    if width <= 0 or height <= 0 or width * height > policy.max_pixels:
        raise ImageValidationError("image dimensions exceed the configured limit")
    return ImageInfo(width=width, height=height, format=image_format, byte_length=len(data))


def _validate_matchable_content(data: bytes, label: str) -> None:
    """Reject exactly uniform images that make normalized correlation meaningless."""

    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            # ddddocr 1.6.1 converts inputs to RGB before edge extraction, so
            # alpha-only variation cannot rescue an otherwise uniform image.
            extrema = image.convert("RGB").getextrema()
    except Exception as exc:
        raise ImageValidationError(f"{label} image cannot be inspected") from exc
    if all(low == high for low, high in extrema):
        raise SolverError(f"{label} image has no visual variation to match")


def _download_image(url: str, policy: DownloadPolicy, session: Any = None) -> Tuple[bytes, ImageInfo]:
    parsed = policy.validate_url(url)
    try:
        import requests
    except ImportError as exc:
        raise DownloadError("requests is required for image downloads") from exc

    client = session or requests.Session()
    response = None
    try:
        response = client.get(
            url,
            allow_redirects=False,
            headers={"Accept": "image/png,image/jpeg,image/webp"},
            stream=True,
            timeout=(policy.connect_timeout, policy.read_timeout),
        )
        if 300 <= response.status_code < 400:
            raise DownloadError("image redirects are not permitted")
        response.raise_for_status()

        media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if not media_type.startswith("image/"):
            raise DownloadError("response Content-Type is not an image")
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError as exc:
                raise DownloadError("invalid Content-Length header") from exc
            if declared_length < 0 or declared_length > policy.max_bytes:
                raise DownloadError("declared image size exceeds the configured limit")

        chunks = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            chunks.extend(chunk)
            if len(chunks) > policy.max_bytes:
                raise DownloadError("image stream exceeds the configured byte limit")
        data = bytes(chunks)
        info = _validate_image_bytes(data, policy)
        return data, info
    except CaptchaSafeError:
        raise
    except requests.RequestException as exc:
        raise DownloadError(f"failed to download image from {parsed.hostname}") from exc
    finally:
        if response is not None and callable(getattr(response, "close", None)):
            response.close()
        if session is None:
            client.close()


def _coerce_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SolverError(f"matcher field {field!r} is not a finite number")
    rounded = int(round(value))
    if abs(value - rounded) > 1e-6:
        raise SolverError(f"matcher field {field!r} is not an integer coordinate")
    return rounded


def _validate_match_result(
    raw: Any,
    target_info: ImageInfo,
    background_info: ImageInfo,
    min_confidence: float,
) -> DistanceResult:
    if not isinstance(raw, Mapping):
        raise SolverError("matcher returned a non-object result")
    expected_fields = {"target", "target_x", "target_y", "confidence"}
    if set(raw) != expected_fields:
        raise SolverError("matcher result does not match the pinned ddddocr 1.6.1 schema")
    target = raw.get("target")
    if not isinstance(target, Sequence) or isinstance(target, (str, bytes)) or len(target) != 2:
        raise SolverError("matcher result must contain a two-coordinate target center")
    center_x, center_y = (
        _coerce_int(value, f"target[{index}]") for index, value in enumerate(target)
    )
    target_x = _coerce_int(raw.get("target_x"), "target_x")
    target_y = _coerce_int(raw.get("target_y"), "target_y")
    if (target_x, target_y) != (center_x, center_y):
        raise SolverError("matcher center fields disagree")

    confidence_raw = raw.get("confidence")
    if (
        isinstance(confidence_raw, bool)
        or not isinstance(confidence_raw, (int, float))
        or not math.isfinite(confidence_raw)
    ):
        raise SolverError("matcher confidence is not a finite number")
    confidence = float(confidence_raw)
    if not -1.0 <= confidence <= 1.0:
        raise SolverError("matcher confidence is outside the normalized range")
    if confidence < min_confidence:
        raise SolverError(
            f"matcher confidence {confidence:.3f} is below the required {min_confidence:.3f}"
        )

    if (
        target_info.width > background_info.width
        or target_info.height > background_info.height
    ):
        raise SolverError("target image is larger than the background")
    minimum_x = target_info.width // 2
    minimum_y = target_info.height // 2
    maximum_x = background_info.width - ((target_info.width + 1) // 2)
    maximum_y = background_info.height - ((target_info.height + 1) // 2)
    if not (
        minimum_x <= center_x <= maximum_x
        and minimum_y <= center_y <= maximum_y
    ):
        raise SolverError("matcher target center cannot contain the target image within the background")
    return DistanceResult(
        target_x=target_x,
        target_y=target_y,
        target=(center_x, center_y),
        confidence=confidence,
        target_image=target_info,
        background_image=background_info,
    )


def _validate_min_confidence(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PolicyError("minimum confidence must be a finite number")
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise PolicyError("minimum confidence must be between 0 and 1")
    return normalized


def _calculate_validated_pair(
    shadow_bytes: bytes,
    background_bytes: bytes,
    target_info: ImageInfo,
    background_info: ImageInfo,
    *,
    ocr_factory: Optional[Callable[[], Any]],
    min_confidence: float,
) -> DistanceResult:
    if (
        target_info.width > background_info.width
        or target_info.height > background_info.height
    ):
        raise SolverError("target image is larger than the background")
    _validate_matchable_content(shadow_bytes, "target")
    _validate_matchable_content(background_bytes, "background")

    if ocr_factory is None:
        try:
            import ddddocr
        except ImportError as exc:
            raise SolverError("ddddocr is required for distance calculation") from exc
        ocr_factory = lambda: ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)

    try:
        matcher = ocr_factory()
        raw = matcher.slide_match(shadow_bytes, background_bytes)
    except CaptchaSafeError:
        raise
    except Exception as exc:
        raise SolverError("the image matcher failed") from exc
    return _validate_match_result(raw, target_info, background_info, min_confidence)


def calculate_distance_from_bytes(
    shadow_bytes: bytes,
    background_bytes: bytes,
    *,
    policy: Optional[DownloadPolicy] = None,
    ocr_factory: Optional[Callable[[], Any]] = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> DistanceResult:
    """Calculate a match after validating both image payloads."""

    effective_policy = policy or DownloadPolicy()
    effective_min_confidence = _validate_min_confidence(min_confidence)
    target_info = _validate_image_bytes(shadow_bytes, effective_policy)
    background_info = _validate_image_bytes(background_bytes, effective_policy)
    return _calculate_validated_pair(
        shadow_bytes,
        background_bytes,
        target_info,
        background_info,
        ocr_factory=ocr_factory,
        min_confidence=effective_min_confidence,
    )


def calculate_distance_from_urls(
    shadow_url: str,
    background_url: str,
    *,
    policy: Optional[DownloadPolicy] = None,
    session: Any = None,
    ocr_factory: Optional[Callable[[], Any]] = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> DistanceResult:
    """Download an approved image pair and return a validated result."""

    effective_policy = policy or DownloadPolicy()
    effective_min_confidence = _validate_min_confidence(min_confidence)
    shadow_bytes, shadow_info = _download_image(shadow_url, effective_policy, session=session)
    background_bytes, background_info = _download_image(background_url, effective_policy, session=session)

    return _calculate_validated_pair(
        shadow_bytes,
        background_bytes,
        shadow_info,
        background_info,
        ocr_factory=ocr_factory,
        min_confidence=effective_min_confidence,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calculate a validated slider match in original-image pixels")
    parser.add_argument("shadow_url", help="approved HTTPS URL of the target/puzzle image")
    parser.add_argument("background_url", help="approved HTTPS URL of the background image")
    parser.add_argument(
        "--allowed-host",
        action="append",
        dest="allowed_hosts",
        help="approved image host; may be repeated (default: static-captcha.aliyuncs.com)",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        policy = DownloadPolicy(
            allowed_hosts=tuple(args.allowed_hosts or DEFAULT_IMAGE_HOSTS),
            max_bytes=args.max_bytes,
        )
        result = calculate_distance_from_urls(
            args.shadow_url,
            args.background_url,
            policy=policy,
            min_confidence=args.min_confidence,
        )
    except PolicyError as exc:
        print(f"input rejected: {exc}", file=sys.stderr)
        return 2
    except DownloadError as exc:
        print(f"download failed: {exc}", file=sys.stderr)
        return 3
    except (ImageValidationError, SolverError) as exc:
        print(f"calculation failed: {exc}", file=sys.stderr)
        return 4

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"target center: {result.target}")
        print(f"match confidence: {result.confidence:.3f}")
        print("note: the center is in original-image pixels and still requires DOM geometry conversion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
