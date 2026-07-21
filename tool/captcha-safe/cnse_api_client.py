#!/usr/bin/env python3
"""CNSE organisation lookup over HTTP APIs, without Chrome or page scripting.

The request and response contracts mirror ``extension/src/cnse-api-recognizer.js``.
One ``requests.Session`` is retained for the challenge and the corresponding
search request because the server binds those two operations together.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import math
import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from cnse_opencv_solver import (
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
DEFAULT_TIMEOUT: Tuple[float, float] = (5.0, 20.0)
MAX_CHALLENGE_BYTES = 16 * 1024 * 1024
MAX_QUERY_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BASE64_CHARACTERS = 12_000_000
ROW_FIELDS = ("dwid", "fzjg", "zsyxq", "dwmc", "dwlb", "sjgxsj", "zsyxqyz")


class CnseApiError(RuntimeError):
    """Base class for errors safe to expose to a command-line caller."""


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


def _bounded_json_response(response: Any, *, limit: int, label: str) -> Any:
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
    iterator = getattr(response, "iter_content", None)
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
        session: Any = None,
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
        self._owns_session = session is None
        if session is None:
            try:
                import requests
            except ImportError as exc:
                raise CnseConfigurationError("requests is required for CNSE API access") from exc
            session = requests.Session()
        self.session = session

    def __enter__(self) -> "CnseApiClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_session and callable(getattr(self.session, "close", None)):
            self.session.close()

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
            response = self.session.request(
                method,
                self._url(path),
                headers=headers,
                data=data,
                allow_redirects=False,
                stream=True,
                timeout=self.timeout,
            )
            return _bounded_json_response(response, limit=limit, label=path.rsplit("/", 1)[-1])
        except CnseApiError:
            raise
        except Exception as exc:
            raise CnseRequestError(f"CNSE request failed: {path.rsplit('/', 1)[-1]}") from exc
        finally:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()

    def fetch_challenge(self) -> CnseChallenge:
        data = self._request_json("GET", CAPTCHA_PATH, limit=MAX_CHALLENGE_BYTES)
        expected = {"bigImage", "errcode", "errmsg", "smallImage", "yHeight"}
        if (
            not isinstance(data, Mapping)
            or set(data) != expected
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
        move_length = match_x - 1
        total, rows = self.submit_search(normalized_keyword, move_length)
        return CnseQueryResult(
            keyword=normalized_keyword,
            total=total,
            rows=rows,
            move_length=move_length,
            api_y_height=challenge.y_height,
            confidence=matched.confidence,
            match_box={
                "x": match_x,
                "y": match_y,
                "width": matched.width,
                "height": matched.height,
            },
            target_center={"x": matched.target_x, "y": matched.target_y},
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query CNSE organisation data using HTTP APIs")
    parser.add_argument("keyword", help="organisation name")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN, choices=sorted(ALLOWED_ORIGINS))
    parser.add_argument("--min-confidence", type=float, default=0.50)
    parser.add_argument("--json", action="store_true", help="emit compact JSON")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        with CnseApiClient(origin=args.origin, min_confidence=args.min_confidence) as client:
            result = client.query(args.keyword).to_dict()
    except CnseConfigurationError as exc:
        print(f"input rejected: {exc}", file=sys.stderr)
        return 2
    except CnseRequestError as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        return 3
    except CnseApiError as exc:
        print(f"query failed: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:
        # Image validation and matcher errors are already scrubbed by calculate_distance.
        print(f"query failed: {exc}", file=sys.stderr)
        return 4

    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
