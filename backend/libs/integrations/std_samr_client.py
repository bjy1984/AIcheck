"""National Standards Information Platform (std.samr.gov.cn) lookup client.

Queries the public search page and category detail pages. There is no stable
JSON search API; responses are parsed from SSR HTML with stdlib only.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from libs.contracts.responses import business_today

DEFAULT_ORIGIN = "https://std.samr.gov.cn"
ALLOWED_ORIGINS = frozenset({DEFAULT_ORIGIN})
SEARCH_PATH = "/search/stdPage"
DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 20.0)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_QUERY_BYTES = 512

DETAIL_PATHS = {
    "BV_GB": "/gb/search/gbDetailed",
    "BV_HB": "/hb/search/stdHBDetailed",
    "BV_DB": "/db/search/stdDBDetailed",
}

STATUS_CURRENT = "现行"
STATUS_UPCOMING = "即将实施"
STATUS_WITHDRAWN = "废止"
STATUS_REPLACED = "被代替"

_STANDARD_REF_RE = re.compile(
    r"(?P<family>(?:GB|HG|NB|JB|SH|SY|DL|HJ|CJ|JG|QB|TB|MT|AQ|SN|WS|NY|LS)"
    r"(?:\s*/\s*T)?)"
    r"\s*"
    r"(?P<number>\d+(?:\.\d+)*)"
    r"(?:\s*[-—－]\s*(?P<year>\d{4}))?",
    re.IGNORECASE,
)
_PANEL_SPLIT_RE = re.compile(
    r'<div class="panel panel-default post">',
    re.IGNORECASE,
)
_TID_PID_RE = re.compile(
    r'tid="(?P<tid>[^"]+)"\s+pid="(?P<pid>[^"]+)"[^>]*>\s*'
    r'<span class="en-code">(?P<code_html>.*?)</span>\s*&nbsp;&nbsp;(?P<name>[^<]*)',
    re.IGNORECASE | re.DOTALL,
)
_STATUS_RE = re.compile(
    r'<span class="s-status[^"]*">(?P<status>[^<]+)</span>',
    re.IGNORECASE,
)
_ISSUE_RE = re.compile(
    r"发布于</span>\s*<time[^>]*>\s*(?P<date>\d{4}-\d{2}-\d{2})\s*</time>",
    re.IGNORECASE,
)
_EFFECTIVE_RE = re.compile(
    r"实施于</span>\s*<time[^>]*>\s*(?P<date>\d{4}-\d{2}-\d{2})\s*</time>",
    re.IGNORECASE,
)
_TOTAL_RE = re.compile(
    r"为您找到相关结果约&nbsp;<span>(?P<total>\d+)</span>",
    re.IGNORECASE,
)
_STATE_VAR_RE = re.compile(r"var STATE='(?P<state>[^']*)'")
_BASIC_INFO_RE = re.compile(
    r'<dt class="basicInfo-item name">(?P<name>[^<]+)</dt>\s*'
    r'<dd class="basicInfo-item value">(?P<value>.*?)</dd>',
    re.IGNORECASE | re.DOTALL,
)
_WHITESPACE_RE = re.compile(r"\s+")


class StdSamrApiError(RuntimeError):
    """Base class for controlled std.samr.gov.cn integration errors."""


class StdSamrConfigurationError(StdSamrApiError):
    """Raised when local client configuration is invalid."""


class StdSamrRequestError(StdSamrApiError):
    """Raised when an HTTP request cannot be completed safely."""


class StdSamrProtocolError(StdSamrApiError):
    """Raised when the upstream returns an unexpected response contract."""


@dataclass(frozen=True)
class CanonicalStandardRef:
    family: str
    number: str
    year: int | None
    raw: str

    @property
    def display(self) -> str:
        base = f"{self.family} {self.number}"
        if self.year is None:
            return base
        return f"{base}-{self.year}"

    @property
    def identity_key(self) -> str:
        return f"{self.family}|{self.number}".upper()

    @property
    def version_key(self) -> str:
        year = str(self.year) if self.year is not None else ""
        return f"{self.identity_key}|{year}"


@dataclass(frozen=True)
class StdSamrBrief:
    tid: str
    pid: str
    code: str
    name: str
    status: str
    issue_date: str | None = None
    effective_date: str | None = None

    def detail_path(self) -> str:
        path = DETAIL_PATHS.get(self.tid)
        if path is None:
            raise StdSamrProtocolError(f"unsupported standard type: {self.tid}")
        return f"{path}?id={self.pid}"

    def to_dict(self, *, origin: str = DEFAULT_ORIGIN) -> Mapping[str, Any]:
        return {
            "tid": self.tid,
            "pid": self.pid,
            "code": self.code,
            "name": self.name,
            "status": self.status,
            "issueDate": self.issue_date,
            "effectiveDate": self.effective_date,
            "detailUrl": urljoin(f"{origin}/", self.detail_path().lstrip("/")),
        }


@dataclass(frozen=True)
class StdSamrSearchResult:
    query: str
    total: int
    rows: tuple[StdSamrBrief, ...]

    def to_dict(self, *, origin: str = DEFAULT_ORIGIN) -> Mapping[str, Any]:
        return {
            "status": "COMPLETED",
            "query": self.query,
            "queryEndpoint": SEARCH_PATH,
            "total": self.total,
            "rows": [dict(row.to_dict(origin=origin)) for row in self.rows],
        }


@dataclass(frozen=True)
class StdSamrDetail:
    tid: str
    pid: str
    code: str
    name: str
    status: str
    issue_date: str | None = None
    effective_date: str | None = None
    withdrawn_on: str | None = None
    supersedes: tuple[str, ...] = ()
    fields: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self, *, origin: str = DEFAULT_ORIGIN) -> Mapping[str, Any]:
        path = DETAIL_PATHS.get(self.tid, SEARCH_PATH)
        return {
            "tid": self.tid,
            "pid": self.pid,
            "code": self.code,
            "name": self.name,
            "status": self.status,
            "issueDate": self.issue_date,
            "effectiveDate": self.effective_date,
            "withdrawnOn": self.withdrawn_on,
            "supersedes": list(self.supersedes),
            "fields": dict(self.fields),
            "detailUrl": urljoin(f"{origin}/", f"{path.lstrip('/')}?id={self.pid}"),
        }


@dataclass(frozen=True)
class StdSamrVerifyResult:
    cited_ref: str
    canonical_ref: str
    verdict: str
    matched: StdSamrBrief | None
    current_execution: StdSamrBrief | None
    standard_references: tuple[Mapping[str, Any], ...]
    detail: StdSamrDetail | None = None
    queried_at: str = ""

    def to_dict(self, *, origin: str = DEFAULT_ORIGIN) -> Mapping[str, Any]:
        return {
            "status": "COMPLETED",
            "citedRef": self.cited_ref,
            "canonicalRef": self.canonical_ref,
            "verdict": self.verdict,
            "matched": None if self.matched is None else dict(self.matched.to_dict(origin=origin)),
            "currentExecution": (
                None
                if self.current_execution is None
                else dict(self.current_execution.to_dict(origin=origin))
            ),
            "standardReferences": [dict(item) for item in self.standard_references],
            "detail": None if self.detail is None else dict(self.detail.to_dict(origin=origin)),
            "queryEndpoint": SEARCH_PATH,
            "queriedAt": self.queried_at,
        }


class _StripTagsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def _strip_tags(value: str) -> str:
    parser = _StripTagsParser()
    parser.feed(value)
    parser.close()
    return _WHITESPACE_RE.sub(" ", parser.text()).strip()


def _normalize_origin(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise StdSamrConfigurationError("std.samr origin is missing")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise StdSamrConfigurationError("std.samr origin is invalid") from exc
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
        raise StdSamrConfigurationError("std.samr origin must be an approved HTTPS origin")
    origin = f"https://{parsed.hostname.lower()}"
    if origin not in ALLOWED_ORIGINS:
        raise StdSamrConfigurationError("std.samr origin is outside the approved scope")
    return origin


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
        raise StdSamrConfigurationError("timeouts must be two positive finite numbers")
    return float(timeout[0]), float(timeout[1])


def normalize_standard_ref(value: str) -> CanonicalStandardRef:
    """Normalize a cited standard code into a canonical family/number/year form."""

    if not isinstance(value, str):
        raise StdSamrConfigurationError("standardRef must be text")
    cleaned = (
        value.replace("—", "-")
        .replace("－", "-")
        .replace("∕", "/")
        .strip()
    )
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\bGBT\b", "GB/T", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bNBT\b", "NB/T", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bJBT\b", "JB/T", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bGBT(?=\s*[\d])", "GB/T ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bNBT(?=\s*[\d])", "NB/T ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bJBT(?=\s*[\d])", "JB/T ", cleaned, flags=re.IGNORECASE)
    if not cleaned or len(cleaned.encode("utf-8")) > MAX_QUERY_BYTES:
        raise StdSamrConfigurationError("请输入有效的标准编号")
    match = _STANDARD_REF_RE.search(cleaned)
    if match is None:
        raise StdSamrConfigurationError("请输入有效的标准编号")
    family_raw = match.group("family").upper().replace(" ", "")
    if "/" in family_raw:
        head, _, tail = family_raw.partition("/")
        family = f"{head}/T" if tail.startswith("T") else head
    else:
        family = family_raw
    number = match.group("number")
    year_raw = match.group("year")
    year = int(year_raw) if year_raw else None
    return CanonicalStandardRef(family=family, number=number, year=year, raw=cleaned)


def normalize_query(value: str) -> str:
    """Normalize a free-text search query within byte limits."""

    if not isinstance(value, str):
        raise StdSamrConfigurationError("query must be text")
    cleaned = _WHITESPACE_RE.sub(" ", value.strip())
    if not cleaned or len(cleaned.encode("utf-8")) > MAX_QUERY_BYTES:
        raise StdSamrConfigurationError("请输入有效的检索关键词")
    return cleaned


def parse_review_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        raise StdSamrConfigurationError("reviewDate must be YYYY-MM-DD")
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise StdSamrConfigurationError("reviewDate must be YYYY-MM-DD") from exc


def parse_search_html(html: str) -> tuple[int, tuple[StdSamrBrief, ...]]:
    if not isinstance(html, str) or not html.strip():
        raise StdSamrProtocolError("std.samr search page is empty")
    total_match = _TOTAL_RE.search(html)
    total = int(total_match.group("total")) if total_match else 0
    panels = _PANEL_SPLIT_RE.split(html)
    rows: list[StdSamrBrief] = []
    for panel in panels[1:]:
        match = _TID_PID_RE.search(panel)
        if match is None:
            continue
        code = _strip_tags(match.group("code_html"))
        name = _WHITESPACE_RE.sub(" ", match.group("name")).strip()
        status_match = _STATUS_RE.search(panel)
        status = (status_match.group("status").strip() if status_match else "") or ""
        issue_match = _ISSUE_RE.search(panel)
        effective_match = _EFFECTIVE_RE.search(panel)
        rows.append(
            StdSamrBrief(
                tid=match.group("tid").strip(),
                pid=match.group("pid").strip(),
                code=code,
                name=name,
                status=status,
                issue_date=issue_match.group("date") if issue_match else None,
                effective_date=effective_match.group("date") if effective_match else None,
            )
        )
    if total == 0:
        total = len(rows)
    return total, tuple(rows)


def parse_detail_html(html: str, *, tid: str, pid: str) -> StdSamrDetail:
    if not isinstance(html, str) or not html.strip():
        raise StdSamrProtocolError("std.samr detail page is empty")
    fields: dict[str, str] = {}
    for match in _BASIC_INFO_RE.finditer(html):
        name = match.group("name").strip()
        value = _strip_tags(match.group("value"))
        if name and value:
            fields[name] = value
    state_match = _STATE_VAR_RE.search(html)
    status = (state_match.group("state").strip() if state_match else "") or fields.get("标准状态", "")
    code = fields.get("标准号") or ""
    if not code:
        raise StdSamrProtocolError("std.samr detail page is missing standard code")
    supersedes_raw = fields.get("全部代替标准") or fields.get("代替标准") or ""
    supersedes = tuple(
        item.strip()
        for item in re.split(r"[,，;；、\n]+", supersedes_raw)
        if item.strip()
    )
    title_match = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
    name = ""
    if title_match:
        title = _WHITESPACE_RE.sub(" ", title_match.group(1)).strip()
        name = title.split("_", 1)[0].strip()
    return StdSamrDetail(
        tid=tid,
        pid=pid,
        code=code,
        name=name or code,
        status=status,
        issue_date=_first_date(fields.get("发布日期")),
        effective_date=_first_date(fields.get("实施日期")),
        withdrawn_on=_first_date(fields.get("废止日期")),
        supersedes=supersedes,
        fields=fields,
    )


def _first_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    return match.group(0) if match else None


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _same_identity(left: CanonicalStandardRef, right: CanonicalStandardRef) -> bool:
    return left.identity_key == right.identity_key


def _brief_canonical(brief: StdSamrBrief) -> CanonicalStandardRef | None:
    try:
        return normalize_standard_ref(brief.code)
    except StdSamrConfigurationError:
        return None


def _status_rank(status: str) -> int:
    mapping = {
        STATUS_CURRENT: 0,
        STATUS_UPCOMING: 1,
        STATUS_REPLACED: 2,
        STATUS_WITHDRAWN: 3,
    }
    return mapping.get(status, 9)


def _pick_current(candidates: list[StdSamrBrief]) -> StdSamrBrief | None:
    ordered = sorted(candidates, key=lambda item: (_status_rank(item.status), item.code))
    for item in ordered:
        if item.status == STATUS_CURRENT:
            return item
    for item in ordered:
        if item.status == STATUS_UPCOMING:
            return item
    return ordered[0] if ordered else None


def _bounded_text_response(response: httpx.Response, *, limit: int, label: str) -> str:
    status = getattr(response, "status_code", None)
    if not isinstance(status, int):
        raise StdSamrRequestError(f"{label} returned no HTTP status")
    if 300 <= status < 400:
        raise StdSamrRequestError(f"{label} redirects are not permitted")
    if not 200 <= status < 300:
        raise StdSamrRequestError(f"{label} returned HTTP {status}")

    declared = getattr(response, "headers", {}).get("Content-Length")
    if declared:
        try:
            declared_length = int(declared)
        except ValueError as exc:
            raise StdSamrRequestError(f"{label} returned an invalid Content-Length") from exc
        if declared_length < 0 or declared_length > limit:
            raise StdSamrRequestError(f"{label} response is too large")

    body = bytearray()
    iterator = getattr(response, "iter_bytes", None)
    if not callable(iterator):
        raise StdSamrRequestError(f"{label} returned an unreadable response")
    for chunk in iterator(chunk_size=64 * 1024):
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > limit:
            raise StdSamrRequestError(f"{label} response is too large")
    try:
        return bytes(body).decode("utf-8")
    except UnicodeDecodeError:
        return bytes(body).decode("gb18030", errors="replace")


class StdSamrClient:
    """Narrowly scoped client for std.samr.gov.cn standard status lookup."""

    def __init__(
        self,
        *,
        origin: str = DEFAULT_ORIGIN,
        client: httpx.Client | None = None,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    ) -> None:
        self.origin = _normalize_origin(origin)
        self.timeout = _validate_timeout(timeout)
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

    def __enter__(self) -> StdSamrClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _url(self, path: str) -> str:
        url = urljoin(f"{self.origin}/", path.lstrip("/"))
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc.lower()}"
        if origin != self.origin:
            raise StdSamrConfigurationError("request path escaped the approved std.samr origin")
        return url

    def _request_text(self, path: str, *, params: Mapping[str, str] | None = None) -> str:
        response = None
        try:
            request = self.client.build_request(
                "GET",
                self._url(path),
                headers={
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    "User-Agent": "AICheck-StdSamrClient/1.0",
                    "Referer": self._url("/search/std"),
                },
                params=params,
            )
            response = self.client.send(request, stream=True, follow_redirects=False)
            return _bounded_text_response(
                response,
                limit=MAX_RESPONSE_BYTES,
                label=path.rsplit("/", 1)[-1],
            )
        except StdSamrApiError:
            raise
        except Exception as exc:
            raise StdSamrRequestError(f"std.samr request failed: {path.rsplit('/', 1)[-1]}") from exc
        finally:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()

    def search(self, query: str, *, page: int = 1) -> StdSamrSearchResult:
        normalized = normalize_query(query)
        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 100_000:
            raise StdSamrConfigurationError("page must be a positive integer")
        params = {"q": normalized}
        if page != 1:
            params["pageNo"] = str(page)
        html = self._request_text(SEARCH_PATH, params=params)
        total, rows = parse_search_html(html)
        return StdSamrSearchResult(query=normalized, total=total, rows=rows)

    def get_detail(self, tid: str, pid: str) -> StdSamrDetail:
        if not isinstance(tid, str) or tid not in DETAIL_PATHS:
            raise StdSamrConfigurationError("unsupported standard type")
        if not isinstance(pid, str) or not re.fullmatch(r"[0-9A-Fa-f]{16,64}", pid):
            raise StdSamrConfigurationError("detail id is invalid")
        html = self._request_text(DETAIL_PATHS[tid], params={"id": pid})
        return parse_detail_html(html, tid=tid, pid=pid)

    def verify(self, cited_ref: str, *, review_date: date | None = None) -> StdSamrVerifyResult:
        canonical = normalize_standard_ref(cited_ref)
        as_of = review_date or business_today()
        queried_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        search_query = canonical.display
        result = self.search(search_query)
        siblings: list[StdSamrBrief] = []
        exact: list[StdSamrBrief] = []
        for row in result.rows:
            row_ref = _brief_canonical(row)
            if row_ref is None or not _same_identity(canonical, row_ref):
                continue
            siblings.append(row)
            if canonical.year is None or row_ref.year == canonical.year:
                exact.append(row)

        if not siblings and canonical.year is not None:
            # Broaden: search without year.
            broadened = self.search(f"{canonical.family} {canonical.number}")
            for row in broadened.rows:
                row_ref = _brief_canonical(row)
                if row_ref is None or not _same_identity(canonical, row_ref):
                    continue
                siblings.append(row)
                if row_ref.year == canonical.year:
                    exact.append(row)

        if not siblings:
            return StdSamrVerifyResult(
                cited_ref=cited_ref.strip(),
                canonical_ref=canonical.display,
                verdict="not_found",
                matched=None,
                current_execution=None,
                standard_references=(),
                queried_at=queried_at,
            )

        matched: StdSamrBrief | None
        if canonical.year is None:
            matched = _pick_current(siblings)
        elif len(exact) == 1:
            matched = exact[0]
        elif len(exact) > 1:
            return StdSamrVerifyResult(
                cited_ref=cited_ref.strip(),
                canonical_ref=canonical.display,
                verdict="ambiguous",
                matched=exact[0],
                current_execution=_pick_current(siblings),
                standard_references=(),
                queried_at=queried_at,
            )
        else:
            return StdSamrVerifyResult(
                cited_ref=cited_ref.strip(),
                canonical_ref=canonical.display,
                verdict="not_found",
                matched=None,
                current_execution=_pick_current(siblings),
                standard_references=(),
                queried_at=queried_at,
            )

        assert matched is not None
        current = _pick_current(siblings)
        detail: StdSamrDetail | None = None
        try:
            detail = self.get_detail(matched.tid, matched.pid)
        except StdSamrApiError:
            detail = None

        effective_from = (detail.effective_date if detail else None) or matched.effective_date
        withdrawn_on = detail.withdrawn_on if detail else None
        status = (detail.status if detail else None) or matched.status
        replaced_by = None
        if current is not None and current.code != matched.code and status in {STATUS_WITHDRAWN, STATUS_REPLACED}:
            replaced_by = current.code

        effective_date = _parse_iso_date(effective_from)
        withdrawn_date = _parse_iso_date(withdrawn_on)

        if status == STATUS_UPCOMING and effective_date is not None and effective_date > as_of:
            verdict = "not_yet_effective"
        elif status in {STATUS_WITHDRAWN, STATUS_REPLACED}:
            verdict = "superseded"
        elif status == STATUS_CURRENT:
            if effective_date is not None and effective_date > as_of:
                verdict = "not_yet_effective"
            elif withdrawn_date is not None and as_of >= withdrawn_date:
                verdict = "superseded"
            elif current is not None and current.code != matched.code and current.status == STATUS_CURRENT:
                verdict = "superseded"
                replaced_by = current.code
            else:
                verdict = "current"
        else:
            verdict = "ambiguous"

        reference = {
            "standardRef": matched.code,
            "status": status,
            "effectiveFrom": effective_from,
            "withdrawnOn": withdrawn_on,
            "replacedBy": replaced_by,
        }
        return StdSamrVerifyResult(
            cited_ref=cited_ref.strip(),
            canonical_ref=canonical.display,
            verdict=verdict,
            matched=matched,
            current_execution=current,
            standard_references=(reference,),
            detail=detail,
            queried_at=queried_at,
        )
