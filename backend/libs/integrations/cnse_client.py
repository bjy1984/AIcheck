"""CNSE organisation and person lookup over HTTP APIs, without Chrome or page scripting.

Ported from ``tool/captcha-safe/cnse_api_client.py``. One ``httpx.Client`` is
retained for the challenge and corresponding search request because CNSE binds
those two operations together.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import httpx

from libs.integrations.cnse_opencv_solver import (
    ALGORITHM,
    CnseOpenCvError,
    OpenCvMatch,
    solve_opencv_from_bytes,
)


DEFAULT_ORIGIN = "https://cnse.e-cqs.cn"
ALLOWED_ORIGINS = frozenset({DEFAULT_ORIGIN, "https://cnse.samr.gov.cn"})
PAGE_PATH = "/info-pub/pub"
CAPTCHA_PATH = "/info-pub/pub/orgSearchVCodeData.json"
SEARCH_PATH = "/info-pub/pub/orgSearchData.json"
PERSON_CAPTCHA_PATH = "/info-pub/pub/pubQueryVCodeData.json"
PERSON_CHECK_PATH = "/info-pub/pub/checkPubQuerycode.json"
PERSON_SEARCH_PATH = "/info-pub/pub/remotePubQuery.json"
DEFAULT_TIMEOUT: Tuple[float, float] = (5.0, 20.0)
MAX_CHALLENGE_BYTES = 16 * 1024 * 1024
MAX_QUERY_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BASE64_CHARACTERS = 12_000_000
MAX_PERSON_FIELD_BYTES = 1024
ROW_FIELDS = ("dwid", "fzjg", "zsyxq", "dwmc", "dwlb", "sjgxsj", "zsyxqyz")
PERSON_FIELDS = (
    "ryxm",
    "sfzh",
    "ryxb",
    "zsbh",
    "zslb",
    "cyzl",
    "fzjg",
    "fzjgszd",
    "khdw",
    "czxm",
    "pzrq",
    "yxrqs",
    "yxrqz",
    "yxrq",
    "validFlag",
    "sjgxsj",
)
_ID_NUMBER_RE = re.compile(r"^(?:\d{15}|\d{17}[\dX])$")


class CnseApiError(RuntimeError):
    """Base class for controlled CNSE integration errors."""


class CnseConfigurationError(CnseApiError):
    """Raised when local client configuration is invalid."""


class CnseRequestError(CnseApiError):
    """Raised when an HTTP request cannot be completed safely."""


class CnseProtocolError(CnseApiError):
    """Raised when CNSE returns an unexpected response contract."""


class CnseRecognitionError(CnseApiError):
    """Raised when the image match is inconsistent with the challenge."""


@dataclass(frozen=True)
class CnseChallenge:
    y_height: int
    puzzle_bytes: bytes
    background_bytes: bytes


@dataclass(frozen=True)
class CnseQueryResult:
    keyword: str
    total: int
    rows: Tuple[Mapping[str, str], ...]
    move_length: int
    api_y_height: int
    confidence: float
    match_box: Mapping[str, int]
    target_center: Mapping[str, int]

    def to_dict(self) -> Mapping[str, Any]:
        """Return the same public result field names as the extension."""

        return {
            "status": "COMPLETED",
            "algorithm": ALGORITHM,
            "captureMode": "api",
            "confidence": self.confidence,
            "moveLength": self.move_length,
            "apiYHeight": self.api_y_height,
            "keyword": self.keyword,
            "queryEndpoint": SEARCH_PATH,
            "total": self.total,
            "rows": [dict(row) for row in self.rows],
            "targetCenter": dict(self.target_center),
            "matchBox": dict(self.match_box),
        }


@dataclass(frozen=True)
class CnsePersonQueryResult:
    id_number: str
    person: Mapping[str, str]
    move_length: int
    api_y_height: int
    confidence: float
    match_box: Mapping[str, int]
    target_center: Mapping[str, int]

    def to_dict(self) -> Mapping[str, Any]:
        """Return the public person-search contract used by the HTTP route."""

        return {
            "status": "COMPLETED",
            "algorithm": ALGORITHM,
            "captureMode": "api",
            "confidence": self.confidence,
            "moveLength": self.move_length,
            "apiYHeight": self.api_y_height,
            "idNumber": self.id_number,
            "queryEndpoint": PERSON_SEARCH_PATH,
            "person": dict(self.person),
            "targetCenter": dict(self.target_center),
            "matchBox": dict(self.match_box),
        }


def _normalize_origin(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise CnseConfigurationError("CNSE origin is missing")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise CnseConfigurationError("CNSE origin is invalid") from exc
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
        or port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise CnseConfigurationError("CNSE origin must be an approved HTTPS origin")
    origin = f"https://{parsed.hostname.lower()}"
    if origin not in ALLOWED_ORIGINS:
        raise CnseConfigurationError("CNSE origin is outside the approved scope")
    return origin


def normalize_keyword(value: str) -> str:
    """Apply the same keyword normalization and byte limit as the extension."""

    if not isinstance(value, str):
        raise CnseConfigurationError("keyword must be text")
    normalized = value.replace(" ", "").strip()
    if not 1 <= len(normalized.encode("utf-8")) <= 512:
        raise CnseConfigurationError("请输入有效的单位名称")
    return normalized


def normalize_id_number(value: str) -> str:
    """Normalize and validate a mainland China ID number for person search."""

    if not isinstance(value, str):
        raise CnseConfigurationError("idNumber must be text")
    normalized = value.replace(" ", "").strip().upper()
    if not _ID_NUMBER_RE.fullmatch(normalized):
        raise CnseConfigurationError("请输入有效的身份证号")
    return normalized


def _parse_challenge_envelope(data: Any) -> CnseChallenge:
    expected = {"bigImage", "errcode", "errmsg", "smallImage", "yHeight"}
    if (
        not isinstance(data, Mapping)
        or not expected.issubset(data)
        or data.get("errcode") != 0
        or data.get("errmsg") != "success"
        or isinstance(data.get("yHeight"), bool)
        or not isinstance(data.get("yHeight"), int)
        or not 0 <= data["yHeight"] <= 4096
    ):
        raise CnseProtocolError("CNSE captcha API returned an invalid envelope")
    return CnseChallenge(
        y_height=data["yHeight"],
        puzzle_bytes=_decode_base64_image(data["smallImage"], "smallImage"),
        background_bytes=_decode_base64_image(data["bigImage"], "bigImage"),
    )


def _parse_person_record(raw: Any) -> Mapping[str, str]:
    if not isinstance(raw, Mapping):
        raise CnseProtocolError("CNSE person record is invalid")
    person: dict[str, str] = {}
    for field in PERSON_FIELDS:
        value = raw.get(field, "")
        if value is None:
            value = ""
        if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_PERSON_FIELD_BYTES:
            raise CnseProtocolError("CNSE person record is invalid")
        person[field] = value
    return person


def _decode_base64_image(value: Any, field: str) -> bytes:
    if (
        not isinstance(value, str)
        or not 16 <= len(value) <= MAX_IMAGE_BASE64_CHARACTERS
        or len(value) % 4 != 0
    ):
        raise CnseProtocolError(f"CNSE challenge field {field} is invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CnseProtocolError(f"CNSE challenge field {field} is invalid") from exc
    if not decoded:
        raise CnseProtocolError(f"CNSE challenge field {field} is empty")
    return decoded


def _validate_timeout(timeout: Tuple[float, float]) -> Tuple[float, float]:
    if (
        not isinstance(timeout, tuple)
        or len(timeout) != 2
        or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
            or item <= 0
            for item in timeout
        )
    ):
        raise CnseConfigurationError("timeouts must be two positive finite numbers")
    return float(timeout[0]), float(timeout[1])


def _bounded_json_response(response: httpx.Response, *, limit: int, label: str) -> Any:
    status = getattr(response, "status_code", None)
    if not isinstance(status, int):
        raise CnseRequestError(f"{label} returned no HTTP status")
    if 300 <= status < 400:
        raise CnseRequestError(f"{label} redirects are not permitted")
    if not 200 <= status < 300:
        raise CnseRequestError(f"{label} returned HTTP {status}")

    declared = getattr(response, "headers", {}).get("Content-Length")
    if declared:
        try:
            declared_length = int(declared)
        except ValueError as exc:
            raise CnseRequestError(f"{label} returned an invalid Content-Length") from exc
        if declared_length < 0 or declared_length > limit:
            raise CnseRequestError(f"{label} response is too large")

    body = bytearray()
    iterator = getattr(response, "iter_bytes", None)
    if not callable(iterator):
        raise CnseRequestError(f"{label} returned an unreadable response")
    for chunk in iterator(chunk_size=64 * 1024):
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > limit:
            raise CnseRequestError(f"{label} response is too large")
    try:
        return json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CnseProtocolError(f"{label} returned invalid JSON") from exc


class CnseApiClient:
    """Stateful, narrowly scoped client for one or more CNSE API lookups."""

    def __init__(
        self,
        *,
        origin: str = DEFAULT_ORIGIN,
        client: httpx.Client | None = None,
        timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
        solver: Optional[Callable[..., OpenCvMatch]] = None,
        min_confidence: float = 0.50,
    ) -> None:
        self.origin = _normalize_origin(origin)
        self.timeout = _validate_timeout(timeout)
        if (
            isinstance(min_confidence, bool)
            or not isinstance(min_confidence, (int, float))
            or not math.isfinite(min_confidence)
            or not 0.0 <= float(min_confidence) <= 1.0
        ):
            raise CnseConfigurationError("minimum confidence must be between 0 and 1")
        self.min_confidence = float(min_confidence)
        self.solver = solver or solve_opencv_from_bytes
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(
                connect=self.timeout[0],
                read=self.timeout[1],
                write=self.timeout[1],
                pool=self.timeout[0],
            ),
            follow_redirects=False,
        )

    def __enter__(self) -> "CnseApiClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _url(self, path: str) -> str:
        url = urljoin(f"{self.origin}/", path.lstrip("/"))
        if urlsplit(url).scheme + "://" + (urlsplit(url).netloc.lower()) != self.origin:
            raise CnseConfigurationError("request path escaped the approved CNSE origin")
        return url

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        limit: int,
        data: Optional[Mapping[str, str]] = None,
        params: Optional[Mapping[str, str]] = None,
    ) -> Any:
        headers = {
            "Accept": "application/json",
            "Referer": self._url(PAGE_PATH),
            "X-Requested-With": "XMLHttpRequest",
        }
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        response = None
        try:
            request = self.client.build_request(
                method,
                self._url(path),
                headers=headers,
                data=data,
                params=params,
            )
            response = self.client.send(request, stream=True, follow_redirects=False)
            return _bounded_json_response(response, limit=limit, label=path.rsplit("/", 1)[-1])
        except CnseApiError:
            raise
        except Exception as exc:
            raise CnseRequestError(f"CNSE request failed: {path.rsplit('/', 1)[-1]}") from exc
        finally:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()

    def _solve_challenge(self, challenge: CnseChallenge) -> Tuple[int, OpenCvMatch]:
        try:
            matched = self.solver(
                challenge.puzzle_bytes,
                challenge.background_bytes,
                min_confidence=self.min_confidence,
            )
        except CnseOpenCvError as exc:
            raise CnseRecognitionError(str(exc)) from exc
        match_x = matched.left
        match_y = matched.top
        if match_x < 1 or abs(match_y - challenge.y_height) > 4:
            raise CnseRecognitionError("recognized gap does not match the CNSE API challenge")
        return match_x - 1, matched

    def fetch_challenge(self) -> CnseChallenge:
        data = self._request_json("GET", CAPTCHA_PATH, limit=MAX_CHALLENGE_BYTES)
        return _parse_challenge_envelope(data)

    def fetch_person_challenge(self) -> CnseChallenge:
        data = self._request_json("GET", PERSON_CAPTCHA_PATH, limit=MAX_CHALLENGE_BYTES)
        return _parse_challenge_envelope(data)

    def check_person_captcha(self, move_length: int) -> None:
        if isinstance(move_length, bool) or not isinstance(move_length, int) or not 0 <= move_length <= 65_535:
            raise CnseConfigurationError("CNSE query parameters are invalid")
        data = self._request_json(
            "POST",
            PERSON_CHECK_PATH,
            limit=MAX_QUERY_BYTES,
            data={"moveLength": str(move_length)},
        )
        if (
            not isinstance(data, Mapping)
            or data.get("errcode") != 0
            or not isinstance(data.get("errmsg"), str)
        ):
            raise CnseRecognitionError("CNSE person captcha check failed")

    def submit_person_search(self, id_number: str, move_length: int) -> Mapping[str, str]:
        normalized_id = normalize_id_number(id_number)
        if isinstance(move_length, bool) or not isinstance(move_length, int) or not 0 <= move_length <= 65_535:
            raise CnseConfigurationError("CNSE query parameters are invalid")
        data = self._request_json(
            "GET",
            PERSON_SEARCH_PATH,
            limit=MAX_QUERY_BYTES,
            params={"keyword": normalized_id, "moveLength": str(move_length)},
        )
        if (
            not isinstance(data, Mapping)
            or data.get("messageLevel") != "success"
            or not isinstance(data.get("data"), Mapping)
        ):
            message = data.get("messageText") if isinstance(data, Mapping) else None
            if not isinstance(message, str) or not message:
                message = "CNSE person query returned invalid data"
            raise CnseProtocolError(message[:128])
        payload = data["data"]
        if payload.get("type") != "person":
            raise CnseProtocolError("CNSE person query did not return a person record")
        return _parse_person_record(payload.get("data"))

    def submit_search(
        self,
        keyword: str,
        move_length: int,
        *,
        page_number: int = 1,
        page_size: int = 10,
    ) -> Tuple[int, Tuple[Mapping[str, str], ...]]:
        normalized_keyword = normalize_keyword(keyword)
        if (
            isinstance(move_length, bool)
            or not isinstance(move_length, int)
            or not 0 <= move_length <= 65_535
            or isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or not 1 <= page_number <= 100_000
            or isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 100
        ):
            raise CnseConfigurationError("CNSE query parameters are invalid")
        data = self._request_json(
            "POST",
            SEARCH_PATH,
            limit=MAX_QUERY_BYTES,
            data={
                "keyword": normalized_keyword,
                "moveLength": str(move_length),
                "pageNumber": str(page_number),
                "pageSize": str(page_size),
            },
        )
        if (
            not isinstance(data, Mapping)
            or isinstance(data.get("total"), bool)
            or not isinstance(data.get("total"), int)
            or not 0 <= data["total"] <= 1_000_000
            or not isinstance(data.get("rows"), list)
            or len(data["rows"]) > page_size
        ):
            message = data.get("messageText") if isinstance(data, Mapping) else None
            if not isinstance(message, str):
                message = "CNSE organization query returned invalid data"
            raise CnseProtocolError(message[:128])
        rows = []
        for raw_row in data["rows"]:
            if not isinstance(raw_row, Mapping):
                raise CnseProtocolError("CNSE organization row is invalid")
            row = {}
            for field in ROW_FIELDS:
                value = raw_row.get(field)
                if not isinstance(value, str) or len(value.encode("utf-8")) > 1024:
                    raise CnseProtocolError("CNSE organization row is invalid")
                row[field] = value
            rows.append(row)
        return data["total"], tuple(rows)

    def query(self, keyword: str) -> CnseQueryResult:
        normalized_keyword = normalize_keyword(keyword)
        challenge = self.fetch_challenge()
        move_length, matched = self._solve_challenge(challenge)
        total, rows = self.submit_search(normalized_keyword, move_length)
        return CnseQueryResult(
            keyword=normalized_keyword,
            total=total,
            rows=rows,
            move_length=move_length,
            api_y_height=challenge.y_height,
            confidence=matched.confidence,
            match_box={
                "x": matched.left,
                "y": matched.top,
                "width": matched.width,
                "height": matched.height,
            },
            target_center={"x": matched.target_x, "y": matched.target_y},
        )

    def query_person(self, id_number: str) -> CnsePersonQueryResult:
        normalized_id = normalize_id_number(id_number)
        challenge = self.fetch_person_challenge()
        move_length, matched = self._solve_challenge(challenge)
        self.check_person_captcha(move_length)
        person = self.submit_person_search(normalized_id, move_length)
        return CnsePersonQueryResult(
            id_number=normalized_id,
            person=person,
            move_length=move_length,
            api_y_height=challenge.y_height,
            confidence=matched.confidence,
            match_box={
                "x": matched.left,
                "y": matched.top,
                "width": matched.width,
                "height": matched.height,
            },
            target_center={"x": matched.target_x, "y": matched.target_y},
        )
