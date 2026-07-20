#!/usr/bin/env python3
"""Authorised CAPTCHA test runner with fail-closed orchestration.

The browser page is treated as data, never as a command source.  A live drag is
opt-in and a client callback is not reported as success until a configured
backend confirms it.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import re
import secrets
import stat
import string
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote, unquote, urlencode, urlsplit, urlunsplit

from calculate_distance import (
    CaptchaSafeError,
    DistanceResult,
    DownloadPolicy,
    calculate_distance_from_urls,
)


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_HARNESS = PROJECT_ROOT / "ai_studio_code (1).html"
HARNESS_ASSET_NAMES = frozenset({DEFAULT_HARNESS.name, "harness.js", "harness.css"})
REGION_DEFAULT_IMAGE_HOSTS = {
    "cn": ("static-captcha.aliyuncs.com",),
    "sgp": ("static-captcha-sgp.aliyuncs.com",),
}
SCENE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{3,63}$")
PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{3,31}$")
TERMINAL_CLIENT_STATES = frozenset({"CLIENT_PASS", "CLIENT_FAIL", "ERROR"})
MAX_CLIENT_TOKEN_LENGTH = 64_000
MAX_VERIFICATION_RESPONSE_BYTES = 64 * 1024


class RunnerError(RuntimeError):
    """A controlled runner failure suitable for a concise CLI message."""


class ConfigurationError(RunnerError):
    pass


class BrowserProtocolError(RunnerError):
    pass


class GeometryError(RunnerError):
    pass


class VerificationError(RunnerError):
    pass


class UnsupportedChallengeError(RunnerError):
    pass


class _ClientTerminalSignal(Exception):
    def __init__(self, state: Mapping[str, Any]) -> None:
        super().__init__(str(state.get("status") or "terminal client state"))
        self.state = dict(state)


@dataclass(frozen=True)
class BrowserGeometry:
    background_left: float
    background_top: float
    background_width: float
    background_height: float
    background_natural_width: int
    background_natural_height: int
    puzzle_left: float
    puzzle_top: float
    puzzle_width: float
    puzzle_height: float
    track_width: float
    slider_width: float
    device_pixel_ratio: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BrowserGeometry":
        required = {
            "backgroundLeft",
            "backgroundTop",
            "backgroundWidth",
            "backgroundHeight",
            "backgroundNaturalWidth",
            "backgroundNaturalHeight",
            "puzzleLeft",
            "puzzleTop",
            "puzzleWidth",
            "puzzleHeight",
            "trackWidth",
            "sliderWidth",
            "devicePixelRatio",
        }
        if not isinstance(value, Mapping) or not required.issubset(value):
            raise GeometryError("browser did not return a complete geometry snapshot")

        converted: Dict[str, float] = {}
        for key in required:
            raw = value[key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
                raise GeometryError(f"geometry field {key} is not a finite number")
            converted[key] = float(raw)

        integer_fields = ("backgroundNaturalWidth", "backgroundNaturalHeight")
        for key in integer_fields:
            if converted[key] <= 0 or not converted[key].is_integer():
                raise GeometryError(f"geometry field {key} must be a positive integer")

        positive_fields = required - {"backgroundLeft", "backgroundTop", "puzzleLeft", "puzzleTop"}
        if any(converted[key] <= 0 for key in positive_fields):
            raise GeometryError("geometry dimensions must be positive")

        return cls(
            background_left=converted["backgroundLeft"],
            background_top=converted["backgroundTop"],
            background_width=converted["backgroundWidth"],
            background_height=converted["backgroundHeight"],
            background_natural_width=int(converted["backgroundNaturalWidth"]),
            background_natural_height=int(converted["backgroundNaturalHeight"]),
            puzzle_left=converted["puzzleLeft"],
            puzzle_top=converted["puzzleTop"],
            puzzle_width=converted["puzzleWidth"],
            puzzle_height=converted["puzzleHeight"],
            track_width=converted["trackWidth"],
            slider_width=converted["sliderWidth"],
            device_pixel_ratio=converted["devicePixelRatio"],
        )


def image_target_center_to_pointer_distance(target_center_x: int, geometry: BrowserGeometry) -> int:
    """Convert an original-image target center into a validated pointer travel.

    The conversion uses measured image, puzzle and track travel ranges.  It is a
    deterministic baseline, not an attempt to disguise automation behaviour.
    """

    if isinstance(target_center_x, bool) or not isinstance(target_center_x, int):
        raise GeometryError("target center must be an integer image coordinate")
    if not 0 <= target_center_x < geometry.background_natural_width:
        raise GeometryError("target center is outside the background image")

    rendered_aspect = geometry.background_width / geometry.background_height
    natural_aspect = geometry.background_natural_width / geometry.background_natural_height
    if abs(rendered_aspect / natural_aspect - 1.0) > 0.02:
        raise GeometryError("background image appears cropped or non-uniformly scaled")

    scale_x = geometry.background_width / geometry.background_natural_width
    desired_puzzle_center = geometry.background_left + target_center_x * scale_x
    current_puzzle_center = geometry.puzzle_left + geometry.puzzle_width / 2.0
    desired_puzzle_travel = desired_puzzle_center - current_puzzle_center
    puzzle_travel_range = geometry.background_width - geometry.puzzle_width
    pointer_travel_range = geometry.track_width - geometry.slider_width
    if puzzle_travel_range <= 0 or pointer_travel_range <= 0:
        raise GeometryError("puzzle or pointer travel range is not positive")

    tolerance = 1.0
    if desired_puzzle_travel < -tolerance or desired_puzzle_travel > puzzle_travel_range + tolerance:
        raise GeometryError("calculated puzzle target is outside the observed travel range")
    desired_puzzle_travel = min(max(desired_puzzle_travel, 0.0), puzzle_travel_range)
    pointer_distance = desired_puzzle_travel * pointer_travel_range / puzzle_travel_range
    rounded = int(round(pointer_distance))
    if not 0 <= rounded <= math.ceil(pointer_travel_range):
        raise GeometryError("calculated pointer distance is outside the track")
    return rounded


def validate_downloaded_images_against_browser(
    distance_result: DistanceResult,
    geometry: BrowserGeometry,
) -> None:
    """Bind OCR inputs to the browser snapshot before using its coordinates."""

    background = distance_result.background_image
    target = distance_result.target_image
    if (
        background.width != geometry.background_natural_width
        or background.height != geometry.background_natural_height
    ):
        raise GeometryError(
            "downloaded background dimensions do not match the browser challenge"
        )

    scale_x = geometry.background_width / background.width
    scale_y = geometry.background_height / background.height
    expected_width = target.width * scale_x
    expected_height = target.height * scale_y
    width_tolerance = max(3.0, expected_width * 0.15)
    height_tolerance = max(3.0, expected_height * 0.15)
    if (
        abs(expected_width - geometry.puzzle_width) > width_tolerance
        or abs(expected_height - geometry.puzzle_height) > height_tolerance
    ):
        raise GeometryError(
            "downloaded puzzle dimensions do not match the rendered challenge"
        )


def validate_vertical_match_alignment(
    distance_result: DistanceResult,
    geometry: BrowserGeometry,
) -> float:
    """Reject a high-confidence match on a row the puzzle cannot occupy."""

    scale_y = geometry.background_height / geometry.background_natural_height
    matched_center_y = geometry.background_top + distance_result.target_y * scale_y
    puzzle_center_y = geometry.puzzle_top + geometry.puzzle_height / 2.0
    error = matched_center_y - puzzle_center_y
    tolerance = max(3.0, geometry.puzzle_height * 0.15)
    if abs(error) > tolerance:
        raise GeometryError("matched target row does not align with the browser puzzle")
    return error


@dataclass(frozen=True)
class CapturedChallenge:
    shadow_url: str
    background_url: str
    geometry: BrowserGeometry
    slider_element: Any = None


@dataclass
class RunReport:
    attempt_id: str
    user_certify_id: str
    status: str = "INIT"
    image_target_center_x: Optional[int] = None
    image_target_center_y: Optional[int] = None
    match_confidence: Optional[float] = None
    vertical_alignment_error: Optional[float] = None
    pointer_distance: Optional[int] = None
    client_status: Optional[str] = None
    server_verified: Optional[bool] = None
    error: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


class _HarnessRequestHandler(SimpleHTTPRequestHandler):
    server_version = "CaptchaSafeHarness/2"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    @classmethod
    def is_allowed_target(cls, target: str) -> bool:
        try:
            if not isinstance(target, str) or target.startswith("//"):
                return False
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                return False
            path = unquote(parsed.path)
        except (TypeError, ValueError, UnicodeError):
            return False
        if not path.startswith("/") or path.startswith("//"):
            return False
        name = path[1:]
        return "/" not in name and "\\" not in name and name in HARNESS_ASSET_NAMES

    def do_GET(self) -> None:
        if not self.is_allowed_target(self.path):
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if not self.is_allowed_target(self.path):
            self.send_error(404)
            return
        super().do_HEAD()

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://o.alicdn.com https://g.alicdn.com; "
            "style-src 'self' 'unsafe-inline' https://*.alicdn.com; "
            "img-src 'self' data: blob: https://*.alicdn.com https://*.aliyuncs.com https://*.aliyun.com; "
            "font-src 'self' data: https://*.alicdn.com; "
            "connect-src 'self' https://*.alicdn.com https://*.aliyuncs.com https://*.aliyun.com; "
            "frame-src https://*.alicdn.com https://*.aliyuncs.com https://*.aliyun.com; "
            "worker-src 'self' blob:; child-src 'self' blob:; "
            "media-src 'none'; manifest-src 'none'; object-src 'none'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        super().end_headers()


@contextlib.contextmanager
def serve_harness(directory: Path) -> Iterator[str]:
    """Serve the harness from an isolated loopback origin."""

    handler = partial(_HarnessRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, name="captcha-safe-harness", daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _validate_harness_url(value: str, *, allow_loopback: bool) -> str:
    """Validate an operator-deployed copy of the reviewed harness."""

    if not isinstance(value, str) or not value or any(ord(char) < 0x20 for char in value):
        raise ConfigurationError("harness URL is missing or contains control characters")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("harness URL is not valid") from exc
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ConfigurationError("harness URL contains forbidden URL components")
    if not host:
        raise ConfigurationError("harness URL has no host")
    if port is not None and not 1 <= port <= 65535:
        raise ConfigurationError("harness URL has an invalid port")
    is_loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (
        allow_loopback and parsed.scheme == "http" and is_loopback
    ):
        raise ConfigurationError(
            "harness URL must use HTTPS; loopback HTTP requires --allow-loopback-harness"
        )
    try:
        decoded_path = unquote(parsed.path)
    except (UnicodeError, ValueError) as exc:
        raise ConfigurationError("harness URL path is invalid") from exc
    segments = decoded_path.split("/")
    if (
        not decoded_path.startswith("/")
        or "\\" in decoded_path
        or any(segment in {".", ".."} for segment in segments)
        or segments[-1] != DEFAULT_HARNESS.name
    ):
        raise ConfigurationError("harness URL must point to the reviewed harness filename")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _append_page_query(page_url: str, values: Mapping[str, str]) -> str:
    parsed = urlsplit(page_url)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(values), "")
    )


def _validate_public_config(value: Optional[str], name: str, pattern: re.Pattern[str]) -> str:
    if not value or not pattern.fullmatch(value):
        raise ConfigurationError(f"{name} is missing or contains unsupported characters")
    return value


def _wait_until(driver: Any, predicate: Any, timeout: float, description: str) -> Any:
    deadline = time.monotonic() + timeout
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except BrowserProtocolError:
            raise
        except Exception as exc:
            last_error = exc
        time.sleep(0.1)
    if last_error:
        raise BrowserProtocolError(f"timed out waiting for {description}") from last_error
    raise BrowserProtocolError(f"timed out waiting for {description}")


def _read_harness_state(driver: Any) -> Optional[Mapping[str, Any]]:
    value = driver.execute_script(
        "return window.__captchaHarness && window.__captchaHarness.getState"
        " ? window.__captchaHarness.getState() : null;"
    )
    return value if isinstance(value, Mapping) else None


def _read_ready_harness_state(driver: Any, attempt_id: str) -> Optional[Mapping[str, Any]]:
    state = _read_harness_state(driver)
    if not state or state.get("attemptId") != attempt_id:
        return None
    status = state.get("status")
    if status == "READY":
        return state
    if status == "ERROR":
        error = state.get("error")
        code = error.get("code") if isinstance(error, Mapping) else None
        raise BrowserProtocolError(
            f"harness initialization failed: {code or 'unspecified error'}"
        )
    return None


_CHALLENGE_SNAPSHOT_SCRIPT = r"""
const harnessState = window.__captchaHarness && window.__captchaHarness.getState
  ? window.__captchaHarness.getState()
  : null;
function observation(challenge) {
  return { harnessState: harnessState, challenge: challenge };
}
const puzzle = document.getElementById('aliyunCaptcha-puzzle');
const background = document.getElementById('aliyunCaptcha-img');
const slider = document.getElementById('aliyunCaptcha-sliding-slider');
if (!puzzle || !background || !slider) return observation(null);

function assetUrl(element) {
  const direct = element.currentSrc || element.src || element.getAttribute('src');
  if (direct) return direct;
  const match = getComputedStyle(element).backgroundImage.match(/^url\(["']?(.*?)["']?\)$/);
  return match ? match[1] : '';
}
function visible(element) {
  const rect = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  return rect.width > 0 && rect.height > 0 &&
    style.display !== 'none' && style.visibility !== 'hidden';
}

if (!visible(puzzle) || !visible(background) || !visible(slider)) return observation(null);
if (background.tagName !== 'IMG' || !background.complete ||
    background.naturalWidth <= 0 || background.naturalHeight <= 0) return observation(null);

const shadowUrl = assetUrl(puzzle);
const backgroundUrl = assetUrl(background);
if (!shadowUrl || !backgroundUrl) return observation(null);

const b = background.getBoundingClientRect();
const p = puzzle.getBoundingClientRect();
const s = slider.getBoundingClientRect();
const track = slider.parentElement && slider.parentElement.getBoundingClientRect();
return observation({
  shadowUrl: shadowUrl,
  backgroundUrl: backgroundUrl,
  sliderElement: slider,
  geometry: {
    backgroundLeft: b.left, backgroundTop: b.top,
    backgroundWidth: b.width, backgroundHeight: b.height,
    backgroundNaturalWidth: background.naturalWidth,
    backgroundNaturalHeight: background.naturalHeight,
    puzzleLeft: p.left, puzzleTop: p.top,
    puzzleWidth: p.width, puzzleHeight: p.height,
    trackWidth: track ? track.width : 0,
    sliderWidth: s.width,
    devicePixelRatio: window.devicePixelRatio || 1
  }
});
"""


def _challenge_from_snapshot(value: Any) -> CapturedChallenge:
    if not isinstance(value, Mapping):
        raise BrowserProtocolError("browser returned an invalid challenge snapshot")
    shadow_url = value.get("shadowUrl")
    background_url = value.get("backgroundUrl")
    if not isinstance(shadow_url, str) or not shadow_url:
        raise BrowserProtocolError("challenge puzzle has no usable image URL")
    if not isinstance(background_url, str) or not background_url:
        raise BrowserProtocolError("challenge background has no usable image URL")
    return CapturedChallenge(
        shadow_url=shadow_url,
        background_url=background_url,
        geometry=BrowserGeometry.from_mapping(value.get("geometry")),
        slider_element=value.get("sliderElement"),
    )


def _challenge_is_stable(first: CapturedChallenge, second: CapturedChallenge) -> bool:
    if first.shadow_url != second.shadow_url or first.background_url != second.background_url:
        return False
    if (
        first.geometry.background_natural_width != second.geometry.background_natural_width
        or first.geometry.background_natural_height != second.geometry.background_natural_height
    ):
        return False
    measured_fields = (
        "background_left",
        "background_top",
        "background_width",
        "background_height",
        "puzzle_left",
        "puzzle_top",
        "puzzle_width",
        "puzzle_height",
        "track_width",
        "slider_width",
    )
    return all(
        abs(getattr(first.geometry, field) - getattr(second.geometry, field)) <= 0.5
        for field in measured_fields
    ) and abs(first.geometry.device_pixel_ratio - second.geometry.device_pixel_ratio) <= 0.01


def _capture_challenge(driver: Any, timeout: float, attempt_id: str) -> CapturedChallenge:
    """Capture two stable, atomic snapshots or surface a terminal client state."""

    deadline = time.monotonic() + timeout
    previous: Optional[CapturedChallenge] = None
    last_error: Optional[Exception] = None
    saw_candidate = False

    while time.monotonic() < deadline:
        try:
            observation = driver.execute_script(_CHALLENGE_SNAPSHOT_SCRIPT)
            if not isinstance(observation, Mapping):
                raise BrowserProtocolError("browser returned an invalid atomic observation")
            state = observation.get("harnessState")
            if not isinstance(state, Mapping) or state.get("attemptId") != attempt_id:
                raise BrowserProtocolError("challenge observation is not bound to this attempt")
            status = state.get("status")
            if status in TERMINAL_CLIENT_STATES:
                raise _ClientTerminalSignal(state)
            raw = observation.get("challenge")
            if status == "CHALLENGE_OPEN" and isinstance(raw, Mapping):
                saw_candidate = True
                current = _challenge_from_snapshot(raw)
                if previous is not None and _challenge_is_stable(previous, current):
                    return current
                previous = current
            else:
                previous = None
        except _ClientTerminalSignal:
            raise
        except (BrowserProtocolError, GeometryError) as exc:
            last_error = exc
            previous = None
        time.sleep(0.1)

    if saw_candidate:
        raise BrowserProtocolError("jigsaw challenge did not reach a stable, loaded snapshot") from last_error
    raise UnsupportedChallengeError(
        "no jigsaw challenge was observed; this runner supports Jigsaw mode only"
    )


def _same_challenge_identity(first: CapturedChallenge, second: CapturedChallenge) -> bool:
    return (
        first.shadow_url == second.shadow_url
        and first.background_url == second.background_url
        and first.geometry.background_natural_width == second.geometry.background_natural_width
        and first.geometry.background_natural_height == second.geometry.background_natural_height
    )


def _perform_pointer_drag(driver: Any, distance: int, slider_element: Any = None) -> None:
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By

    slider = slider_element or driver.find_element(By.ID, "aliyunCaptcha-sliding-slider")
    ActionChains(driver).move_to_element(slider).click_and_hold(slider).pause(0.15).move_by_offset(
        distance, 0
    ).pause(0.15).release().perform()


def _click_trigger(driver: Any) -> None:
    from selenium.webdriver.common.by import By

    driver.find_element(By.ID, "button").click()


def _validate_verification_endpoint(endpoint: str) -> None:
    try:
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("verification endpoint is not a valid URL") from exc
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ConfigurationError("verification endpoint contains forbidden URL components")
    is_loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
        raise ConfigurationError("verification endpoint must use HTTPS or loopback HTTP")
    if not host:
        raise ConfigurationError("verification endpoint has no host")
    if port is not None and not 1 <= port <= 65535:
        raise ConfigurationError("verification endpoint has an invalid port")


def verify_with_backend(
    endpoint: str,
    *,
    captcha_verify_param: str,
    scene_id: str,
    region: str,
    user_certify_id: str,
    attempt_id: str,
    session: Any = None,
    timeout: float = 10.0,
) -> bool:
    """Submit an opaque client proof to a user-controlled verification backend."""

    _validate_verification_endpoint(endpoint)
    if region not in REGION_DEFAULT_IMAGE_HOSTS:
        raise VerificationError("client region is invalid")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}", user_certify_id):
        raise VerificationError("user certification correlation ID is invalid")
    if (
        not isinstance(captcha_verify_param, str)
        or not captcha_verify_param
        or len(captcha_verify_param) > MAX_CLIENT_TOKEN_LENGTH
    ):
        raise VerificationError("client verification parameter is missing or oversized")
    try:
        import requests
    except ImportError as exc:
        raise VerificationError("requests is required for backend verification") from exc

    client = session or requests.Session()
    response = None
    try:
        response = client.post(
            endpoint,
            json={
                "captchaVerifyParam": captcha_verify_param,
                "sceneId": scene_id,
                "region": region,
                "userCertifyId": user_certify_id,
                "attemptId": attempt_id,
            },
            timeout=timeout,
            allow_redirects=False,
            stream=True,
            headers={"Accept": "application/json"},
        )
        if 300 <= response.status_code < 400:
            raise VerificationError("verification endpoint redirects are not permitted")
        response.raise_for_status()
        media_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if media_type != "application/json":
            raise VerificationError("verification endpoint returned a non-JSON response")
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError as exc:
                raise VerificationError("verification endpoint returned an invalid Content-Length") from exc
            if declared_length < 0 or declared_length > MAX_VERIFICATION_RESPONSE_BYTES:
                raise VerificationError("verification endpoint response is oversized")

        body = bytearray()
        for chunk in response.iter_content(chunk_size=16 * 1024):
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > MAX_VERIFICATION_RESPONSE_BYTES:
                raise VerificationError("verification endpoint response is oversized")
        try:
            payload = json.loads(bytes(body).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VerificationError("verification backend returned invalid JSON") from exc
    except VerificationError:
        raise
    except requests.RequestException as exc:
        raise VerificationError("verification backend request failed") from exc
    except (TypeError, ValueError) as exc:
        raise VerificationError("verification backend returned invalid JSON") from exc
    finally:
        if response is not None and callable(getattr(response, "close", None)):
            response.close()
        if session is None:
            client.close()

    if not isinstance(payload, Mapping) or not isinstance(payload.get("verified"), bool):
        raise VerificationError("verification backend response lacks a boolean 'verified' field")
    response_attempt = payload.get("attemptId")
    if response_attempt != attempt_id:
        raise VerificationError("verification backend response attempt does not match")
    if payload.get("userCertifyId") != user_certify_id:
        raise VerificationError("verification backend response certification ID does not match")
    return bool(payload["verified"])


def _create_driver(headless: bool) -> Any:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError as exc:
        raise ConfigurationError("selenium is not installed") from exc

    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1440,1000")
    options.add_argument("--incognito")
    if headless:
        options.add_argument("--headless=new")
    return webdriver.Chrome(options=options)


def _load_administrator_public_key(value: Optional[str]) -> bytes:
    """Read a POSIX administrator-controlled trust anchor without a TOCTOU gap."""

    if not value:
        raise ConfigurationError("a trusted --public-key file is required")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigurationError("trusted public-key path must be absolute")
    if os.name != "posix":
        raise ConfigurationError("this build requires a POSIX administrator-managed trust anchor")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(os.fspath(path), flags)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ConfigurationError("trusted public key must be a regular file")
            if info.st_uid != 0:
                raise ConfigurationError("trusted public key must be owned by the system administrator (uid 0)")
            if info.st_mode & 0o022:
                raise ConfigurationError("trusted public key cannot be group/other writable")
            material = handle.read(64 * 1024 + 1)
            if not material or len(material) > 64 * 1024:
                raise ConfigurationError("trusted public key is empty or oversized")
            return material
    except ConfigurationError:
        raise
    except OSError as exc:
        raise ConfigurationError("trusted public key cannot be read safely") from exc


def _require_authorization(args: argparse.Namespace, allowed_hosts: Sequence[str]) -> None:
    """Require a signed licence for every real browser/network challenge."""

    if not args.public_key or not args.license_file:
        raise ConfigurationError("a license file and administrator-managed public key are required")
    try:
        from license_manager import LicenseManager
    except ImportError as exc:
        raise ConfigurationError("license manager is unavailable") from exc

    public_key = _load_administrator_public_key(args.public_key)
    manager = LicenseManager(license_file=Path(args.license_file), public_key=public_key)
    # Preserve the runner's stdout as one machine-readable JSON document.
    with contextlib.redirect_stdout(io.StringIO()):
        valid, error = manager.verify_license(
            required_scene_id=args.scene_id,
            required_hosts=tuple(allowed_hosts),
        )
    if not valid:
        raise ConfigurationError(f"authorization failed: {error}")


def _finish_client_state(
    driver: Any,
    state: Mapping[str, Any],
    args: argparse.Namespace,
    report: RunReport,
) -> Tuple[int, RunReport]:
    report.client_status = str(state.get("status") or "ERROR")
    if report.client_status != "CLIENT_PASS":
        report.status = report.client_status
        error = state.get("error")
        if isinstance(error, Mapping):
            report.error = str(error.get("code") or "client verification failed")
        else:
            report.error = "client verification failed"
        return 5, report

    if not args.execute_drag:
        # A risk engine may legitimately skip the jigsaw. This is a client-only
        # observation, not a claim that server verification succeeded.
        report.status = "NO_JIGSAW_CLIENT_PASS"
        return 0, report

    token = driver.execute_script(
        "return window.__captchaHarness.consumeClientToken(arguments[0]);", report.attempt_id
    )
    if not isinstance(token, str) or not token:
        raise BrowserProtocolError("client callback did not provide a consumable verification parameter")

    verified = verify_with_backend(
        args.verification_endpoint,
        captcha_verify_param=token,
        scene_id=args.scene_id,
        region=args.region,
        user_certify_id=report.user_certify_id,
        attempt_id=report.attempt_id,
        timeout=args.timeout,
    )
    report.server_verified = verified
    report.status = "SERVER_VERIFIED" if verified else "SERVER_REJECTED"
    return (0 if verified else 6), report


def run(args: argparse.Namespace) -> Tuple[int, RunReport]:
    attempt_id = uuid.uuid4().hex
    report = RunReport(attempt_id=attempt_id, user_certify_id="")
    driver = None

    try:
        args.scene_id = _validate_public_config(args.scene_id, "scene ID", SCENE_ID_PATTERN)
        args.prefix = _validate_public_config(args.prefix, "prefix", PREFIX_PATTERN)
        user_certify_id = args.prefix + "_" + "".join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(10)
        )
        report.user_certify_id = user_certify_id
        if isinstance(args.timeout, bool) or not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ConfigurationError("timeout must be a positive finite number")
        if (
            isinstance(args.min_confidence, bool)
            or not isinstance(args.min_confidence, (int, float))
            or not math.isfinite(args.min_confidence)
            or not 0.0 <= args.min_confidence <= 1.0
        ):
            raise ConfigurationError("minimum confidence must be between 0 and 1")
        if args.region not in REGION_DEFAULT_IMAGE_HOSTS:
            raise ConfigurationError("region must be 'cn' or 'sgp'")
        if args.language not in {"cn", "en"}:
            raise ConfigurationError("language must be 'cn' or 'en'")
        if args.harness_url and args.allow_loopback_harness:
            parsed_harness = urlsplit(
                _validate_harness_url(args.harness_url, allow_loopback=True)
            )
        elif args.harness_url:
            parsed_harness = urlsplit(
                _validate_harness_url(args.harness_url, allow_loopback=False)
            )
        elif args.allow_loopback_harness:
            parsed_harness = None
        else:
            raise ConfigurationError(
                "configure an authorised HTTPS --harness-url, or explicitly use "
                "--allow-loopback-harness for a dedicated local test scene"
            )

        allowed_hosts = tuple(
            dict.fromkeys(
                (*REGION_DEFAULT_IMAGE_HOSTS[args.region], *(args.allowed_host or ()))
            )
        )
        try:
            image_policy = DownloadPolicy(
                allowed_hosts=allowed_hosts,
                max_bytes=args.max_image_bytes,
            )
        except CaptchaSafeError as exc:
            raise ConfigurationError(str(exc)) from exc
        if args.execute_drag and not args.verification_endpoint:
            raise ConfigurationError("--execute-drag requires --verification-endpoint before launch")
        verification_host = None
        if args.verification_endpoint:
            _validate_verification_endpoint(args.verification_endpoint)
            verification_host = (urlsplit(args.verification_endpoint).hostname or "").lower()
        harness_host = (parsed_harness.hostname or "").lower() if parsed_harness else "127.0.0.1"
        licensed_hosts = tuple(
            dict.fromkeys(
                (
                    *image_policy.allowed_hosts,
                    harness_host,
                    *((verification_host,) if verification_host else ()),
                )
            )
        )
        _require_authorization(args, licensed_hosts)

        harness_context = (
            contextlib.nullcontext(
                urlunsplit(
                    (
                        parsed_harness.scheme,
                        parsed_harness.netloc,
                        parsed_harness.path,
                        "",
                        "",
                    )
                )
            )
            if parsed_harness
            else serve_harness(PROJECT_ROOT)
        )
        with harness_context as harness_location:
            driver = _create_driver(args.headless)
            page_base = (
                harness_location
                if parsed_harness
                else f"{harness_location}/{quote(DEFAULT_HARNESS.name)}"
            )
            page_url = _append_page_query(
                page_base,
                {
                    "sceneId": args.scene_id,
                    "prefix": args.prefix,
                    "region": args.region,
                    "language": args.language,
                    "attemptId": attempt_id,
                    "userCertifyId": user_certify_id,
                },
            )
            driver.get(page_url)

            state = _wait_until(
                driver,
                lambda: _read_ready_harness_state(driver, attempt_id),
                args.timeout,
                "harness readiness",
            )
            report.status = str(state["status"])

            _click_trigger(driver)
            report.status = "CHALLENGE_OPEN"
            try:
                challenge = _capture_challenge(driver, args.timeout, attempt_id)
            except _ClientTerminalSignal as signal:
                return _finish_client_state(driver, signal.state, args, report)
            image_policy.validate_url(challenge.shadow_url)
            image_policy.validate_url(challenge.background_url)
            distance_result: DistanceResult = calculate_distance_from_urls(
                challenge.shadow_url,
                challenge.background_url,
                policy=image_policy,
                min_confidence=args.min_confidence,
            )
            validate_downloaded_images_against_browser(
                distance_result,
                challenge.geometry,
            )
            vertical_error = validate_vertical_match_alignment(
                distance_result,
                challenge.geometry,
            )
            pointer_distance = image_target_center_to_pointer_distance(
                distance_result.match_center_x,
                challenge.geometry,
            )
            report.image_target_center_x = distance_result.match_center_x
            report.image_target_center_y = distance_result.target_y
            report.match_confidence = distance_result.confidence
            report.vertical_alignment_error = vertical_error
            report.pointer_distance = pointer_distance
            report.status = "DISTANCE_READY"

            if not args.execute_drag:
                return 0, report

            try:
                fresh_challenge = _capture_challenge(driver, args.timeout, attempt_id)
            except _ClientTerminalSignal as signal:
                return _finish_client_state(driver, signal.state, args, report)
            if not _same_challenge_identity(challenge, fresh_challenge):
                raise BrowserProtocolError(
                    "challenge refreshed after matching; refusing to drag using stale coordinates"
                )
            validate_downloaded_images_against_browser(
                distance_result,
                fresh_challenge.geometry,
            )
            report.vertical_alignment_error = validate_vertical_match_alignment(
                distance_result,
                fresh_challenge.geometry,
            )
            pointer_distance = image_target_center_to_pointer_distance(
                distance_result.match_center_x,
                fresh_challenge.geometry,
            )
            report.pointer_distance = pointer_distance
            _perform_pointer_drag(
                driver,
                pointer_distance,
                slider_element=fresh_challenge.slider_element,
            )
            state = _wait_until(
                driver,
                lambda: (
                    current
                    if (current := _read_harness_state(driver))
                    and current.get("attemptId") == attempt_id
                    and current.get("status") in TERMINAL_CLIENT_STATES
                    else None
                ),
                args.timeout,
                "client verification callback",
            )
            return _finish_client_state(driver, state, args, report)
    except ConfigurationError as exc:
        report.status = "CONFIGURATION_ERROR"
        report.error = str(exc)
        return 2, report
    except (BrowserProtocolError, GeometryError) as exc:
        report.status = "BROWSER_ERROR"
        report.error = str(exc)
        return 3, report
    except UnsupportedChallengeError as exc:
        report.status = "UNSUPPORTED_CHALLENGE_TYPE"
        report.error = str(exc)
        return 3, report
    except CaptchaSafeError as exc:
        report.status = "CALCULATION_ERROR"
        report.error = str(exc)
        return 4, report
    except VerificationError as exc:
        report.status = "SERVER_VERIFICATION_ERROR"
        report.error = str(exc)
        return 6, report
    except Exception as exc:
        report.status = "UNEXPECTED_ERROR"
        # Selenium/network exceptions can embed signed URLs or page details.
        report.error = f"unexpected {type(exc).__name__}"
        return 10, report
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an authorised, fail-closed CAPTCHA test")
    parser.add_argument("--scene-id", default=os.environ.get("CAPTCHA_SCENE_ID"))
    parser.add_argument("--prefix", default=os.environ.get("CAPTCHA_PREFIX"))
    parser.add_argument("--region", choices=("cn", "sgp"), default="cn")
    parser.add_argument("--language", choices=("cn", "en"), default="cn")
    parser.add_argument(
        "--harness-url",
        help="authorised HTTPS deployment of the bundled harness (no query string)",
    )
    parser.add_argument(
        "--allow-loopback-harness",
        action="store_true",
        help="serve the bundled harness on random loopback HTTP for a dedicated test scene",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        help="additional exact HTTPS image host; the regional default remains enabled",
    )
    parser.add_argument("--max-image-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--min-confidence", type=float, default=0.50)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--execute-drag",
        action="store_true",
        help="perform the browser action; requires a preconfigured backend verification endpoint",
    )
    parser.add_argument("--license-file", default=str(Path.home() / ".aliyun_captcha_license.json"))
    parser.add_argument(
        "--public-key",
        default=os.environ.get("CAPTCHA_LICENSE_PUBLIC_KEY_FILE"),
        help="absolute path to an administrator/root-owned Ed25519 trust anchor",
    )
    parser.add_argument("--verification-endpoint")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    code, report = run(args)
    if args.pretty:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(report.to_json())
    return code


if __name__ == "__main__":
    raise SystemExit(main())
