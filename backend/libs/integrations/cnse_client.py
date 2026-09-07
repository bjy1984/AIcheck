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
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
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
# 网页流程的后两步：remotePubQuery 只回一条记录（网页只用它取身份证号），
# 全部证书要先打开结果页拿 validCode，再调 getPerInfoBySfzh 取 licList。
# 2026-09-06 实测：李卫伍 remotePubQuery 只回"起重机指挥"，licList 有 7 条（含 3 张现行焊工证）。
PERSON_RESULT_PAGE_PATH = "/info-pub/pub/perResult"
PERSON_INFO_PATH = "/info-pub/pub/getPerInfoBySfzh.json"
DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 20.0)
MAX_CHALLENGE_BYTES = 16 * 1024 * 1024
MAX_QUERY_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BASE64_CHARACTERS = 12_000_000
MAX_PERSON_FIELD_BYTES = 1024
MAX_PAGE_BYTES = 512 * 1024
MAX_LICENSE_COUNT = 200
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
    rows: tuple[Mapping[str, str], ...]
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
    # 全表证书；空元组配合 license_lookup["status"] != "completed" 表示没拿到而不是没有
    licenses: tuple[Mapping[str, str], ...] = ()
    license_lookup: Mapping[str, Any] = None  # type: ignore[assignment]

    def to_dict(self) -> Mapping[str, Any]:
        """Return the public person-search contract used by the HTTP route."""

        lookup = dict(self.license_lookup or {"status": "not_attempted"})
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
            "licenses": [dict(item) for item in self.licenses],
            "licenseCount": len(self.licenses),
            "licenseLookup": lookup,
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


# 单位许可证记录（remotePubQuery.json 以许可证编号为 keyword 时返回 type=organization）。
# 2026-09-06 实测 TS1844171-2028：czzt=有效、zsbh、dwmc、fzjg、zsxkxm=压力管道设计、zsyxq=2028-01-17、tyshxydm。
ORG_LICENSE_FIELDS = (
    "zsbh",  # 证书编号
    "dwmc",  # 单位名称
    "czzt",  # 证照状态（有效/注销/…）
    "dwlb",  # 单位类别
    "fzjg",  # 发证机关
    "xklb",  # 许可类别
    "xkxm",  # 许可项目
    "zsxkxm",  # 证书许可项目
    "zsxkfw",  # 许可范围
    "zsxkfwDesc",
    "zsfzrq",  # 发证日期
    "zsyxq",  # 有效期至
    "zsbgrq",  # 变更日期
    "tyshxydm",  # 统一社会信用代码
    "dwid",
    "sqlb",  # 申请类别（换证/新取证…）
    "validFlag",
    "sjgxsj",
)
_LICENSE_NO_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{4,30}$")


def normalize_license_no(value: str) -> str:
    """许可证编号：去空格、转大写，允许字母数字与连字符（TS1844171-2028）。"""
    if not isinstance(value, str):
        raise CnseConfigurationError("licenseNo must be text")
    normalized = value.replace(" ", "").strip().upper()
    if not _LICENSE_NO_RE.fullmatch(normalized):
        raise CnseConfigurationError("请输入有效的许可证编号")
    return normalized


def _parse_organization_license_record(raw: Any) -> Mapping[str, str]:
    if not isinstance(raw, Mapping):
        raise CnseProtocolError("CNSE organization license record is invalid")
    record: dict[str, str] = {}
    for field in ORG_LICENSE_FIELDS:
        value = raw.get(field, "")
        if value is None:
            value = ""
        if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_PERSON_FIELD_BYTES:
            raise CnseProtocolError("CNSE organization license record is invalid")
        record[field] = value
    return record


@dataclass(frozen=True)
class CnseLicenseQueryResult:
    license_no: str
    found: bool
    record: Mapping[str, str]
    move_length: int
    confidence: float

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "status": "COMPLETED",
            "algorithm": ALGORITHM,
            "captureMode": "api",
            "confidence": self.confidence,
            "moveLength": self.move_length,
            "licenseNo": self.license_no,
            "queryEndpoint": PERSON_SEARCH_PATH,
            "found": self.found,
            "record": dict(self.record),
        }


def _parse_license_record(raw: Any) -> Mapping[str, str]:
    """licList 里的记录字段与 remotePubQuery 相同，但允许缺字段（老证书 khdw/yxrqs 常为空）。"""
    if not isinstance(raw, Mapping):
        raise CnseProtocolError("CNSE license record is invalid")
    record: dict[str, str] = {}
    for field in PERSON_FIELDS:
        value = raw.get(field, "")
        if value is None:
            value = ""
        if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_PERSON_FIELD_BYTES:
            raise CnseProtocolError("CNSE license record is invalid")
        record[field] = value
    for extra in ("limitRange", "remark", "eCertFileId", "khrq", "pzdw"):
        value = raw.get(extra, "")
        if isinstance(value, str) and len(value.encode("utf-8")) <= MAX_PERSON_FIELD_BYTES:
            record[extra] = value
    return record


_VALID_CODE_RE = re.compile(r'id="validCode"\s+value="([0-9a-fA-F]{8,64})"')
_ERRCODE_RE = re.compile(r'id="errcode"\s+value="([^"]*)"')


def _parse_person_result_page(html: str) -> str:
    err = _ERRCODE_RE.search(html)
    if err is None or err.group(1).strip() != "0":
        raise CnseProtocolError("CNSE person result page rejected the captcha session")
    match = _VALID_CODE_RE.search(html)
    if match is None:
        raise CnseProtocolError("CNSE person result page has no validCode")
    return match.group(1)


def _bounded_text_response(response: httpx.Response, *, limit: int, label: str) -> str:
    status = getattr(response, "status_code", None)
    if not isinstance(status, int):
        raise CnseRequestError(f"{label} returned no HTTP status")
    if 300 <= status < 400:
        raise CnseRequestError(f"{label} redirects are not permitted")
    if not 200 <= status < 300:
        raise CnseRequestError(f"{label} returned HTTP {status}")
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
        return bytes(body).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CnseProtocolError(f"{label} returned undecodable text") from exc


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


def _validate_timeout(timeout: tuple[float, float]) -> tuple[float, float]:
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
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        solver: Callable[..., OpenCvMatch] | None = None,
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

    def __enter__(self) -> CnseApiClient:
        return self

    def __exit__(self, *_: object) -> None:
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
        data: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
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

    def _solve_challenge(self, challenge: CnseChallenge) -> tuple[int, OpenCvMatch]:
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
        if (
            isinstance(move_length, bool)
            or not isinstance(move_length, int)
            or not 0 <= move_length <= 65_535
        ):
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
        if (
            isinstance(move_length, bool)
            or not isinstance(move_length, int)
            or not 0 <= move_length <= 65_535
        ):
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
    ) -> tuple[int, tuple[Mapping[str, str], ...]]:
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

    def fetch_person_valid_code(self, id_number: str, move_length: int) -> str:
        """打开人员结果页，取出 getPerInfoBySfzh 需要的 validCode（同一验证码会话内）。"""
        normalized_id = normalize_id_number(id_number)
        headers = {"Referer": self._url(PAGE_PATH)}
        response = None
        try:
            request = self.client.build_request(
                "GET",
                self._url(PERSON_RESULT_PAGE_PATH),
                headers=headers,
                params={"sfzh": normalized_id, "moveLength": str(move_length)},
            )
            response = self.client.send(request, stream=True, follow_redirects=False)
            html = _bounded_text_response(response, limit=MAX_PAGE_BYTES, label="perResult")
        except CnseApiError:
            raise
        except Exception as exc:
            raise CnseRequestError("CNSE request failed: perResult") from exc
        finally:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()
        return _parse_person_result_page(html)

    def fetch_person_licenses(
        self, id_number: str, valid_code: str
    ) -> tuple[Mapping[str, str], ...]:
        normalized_id = normalize_id_number(id_number)
        if not isinstance(valid_code, str) or not re.fullmatch(r"[0-9a-fA-F]{8,64}", valid_code):
            raise CnseConfigurationError("CNSE validCode is invalid")
        data = self._request_json(
            "GET",
            PERSON_INFO_PATH,
            limit=MAX_QUERY_BYTES,
            params={
                "sfzh": normalized_id,
                "validCode": valid_code,
                "r": str(int(time.time() * 1000)),
            },
        )
        payload = data.get("data") if isinstance(data, Mapping) and "licList" not in data else data
        if not isinstance(payload, Mapping) or not isinstance(payload.get("licList"), list):
            raise CnseProtocolError("CNSE person info did not return licList")
        raw_list = payload["licList"]
        if len(raw_list) > MAX_LICENSE_COUNT:
            raise CnseProtocolError("CNSE person info returned too many licenses")
        return tuple(_parse_license_record(item) for item in raw_list)

    def submit_license_search(self, license_no: str, move_length: int) -> Mapping[str, str] | None:
        """以许可证编号为关键字查 remotePubQuery：返回单位许可记录；平台答"未查询到数据"时返回 None。"""
        normalized = normalize_license_no(license_no)
        if isinstance(move_length, bool) or not isinstance(move_length, int) or not 0 <= move_length <= 65_535:
            raise CnseConfigurationError("CNSE query parameters are invalid")
        data = self._request_json(
            "GET",
            PERSON_SEARCH_PATH,
            limit=MAX_QUERY_BYTES,
            params={"keyword": normalized, "moveLength": str(move_length)},
        )
        if not isinstance(data, Mapping):
            raise CnseProtocolError("CNSE license query returned invalid data")
        if data.get("messageLevel") != "success":
            message = data.get("messageText")
            if isinstance(message, str) and "未查询到" in message:
                return None
            raise CnseProtocolError((message if isinstance(message, str) and message else "CNSE license query failed")[:128])
        payload = data.get("data")
        if not isinstance(payload, Mapping) or payload.get("type") != "organization":
            raise CnseProtocolError("CNSE license query did not return an organization record")
        return _parse_organization_license_record(payload.get("data"))

    def query_organization_license(self, license_no: str) -> CnseLicenseQueryResult:
        """许可证编号 → 平台登记的单位许可记录（走人员查询同一套验证码会话）。"""
        normalized = normalize_license_no(license_no)
        challenge = self.fetch_person_challenge()
        move_length, matched = self._solve_challenge(challenge)
        self.check_person_captcha(move_length)
        record = self.submit_license_search(normalized, move_length)
        return CnseLicenseQueryResult(
            license_no=normalized,
            found=record is not None,
            record=record or {},
            move_length=move_length,
            confidence=matched.confidence,
        )

    def query_person(
        self, id_number: str, *, include_licenses: bool = True
    ) -> CnsePersonQueryResult:
        normalized_id = normalize_id_number(id_number)
        challenge = self.fetch_person_challenge()
        move_length, matched = self._solve_challenge(challenge)
        self.check_person_captcha(move_length)
        person = self.submit_person_search(normalized_id, move_length)
        licenses: tuple[Mapping[str, str], ...] = ()
        lookup: dict[str, Any] = {"status": "not_attempted"}
        if include_licenses:
            # 后两步失败不应让第一步的结果作废：降级为"只拿到一条"，并把原因带出去，
            # 让规则层输出"需人工确认"而不是把"未返回焊接项目"当作假证。
            try:
                valid_code = self.fetch_person_valid_code(normalized_id, move_length)
                licenses = self.fetch_person_licenses(normalized_id, valid_code)
                lookup = {"status": "completed", "endpoint": PERSON_INFO_PATH}
            except CnseApiError as exc:
                lookup = {
                    "status": "failed",
                    "endpoint": PERSON_INFO_PATH,
                    "reason": exc.__class__.__name__,
                    "message": str(exc)[:160],
                }
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
            licenses=licenses,
            license_lookup=lookup,
        )
