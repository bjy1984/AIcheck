from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import apps.api.std_samr_routes as std_samr_routes
from apps.api.main import app
from libs.integrations.std_samr_client import (
    StdSamrClient,
    StdSamrConfigurationError,
    normalize_standard_ref,
    parse_detail_html,
    parse_search_html,
)


client = TestClient(app)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "std_samr"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_normalize_standard_ref_accepts_common_variants() -> None:
    assert normalize_standard_ref("GB/T12771-2019").display == "GB/T 12771-2019"
    assert normalize_standard_ref("GB/T 12771—2008").display == "GB/T 12771-2008"
    assert normalize_standard_ref("GBT 12771-2008").display == "GB/T 12771-2008"
    assert normalize_standard_ref("NB/T 47013.8-2025").display == "NB/T 47013.8-2025"
    assert normalize_standard_ref("  nb/t 47013.8 — 2012 ").year == 2012


def test_normalize_standard_ref_rejects_blank() -> None:
    with pytest.raises(StdSamrConfigurationError):
        normalize_standard_ref("   ")


def test_parse_search_html_gbt_12771() -> None:
    total, rows = parse_search_html(fixture_text("stdpage_gbt_12771.html"))
    assert total == 3
    assert [row.code for row in rows] == [
        "GB/T 12771-2019",
        "GB/T 12771-2008",
        "GB/T 12771-2000",
    ]
    assert rows[0].status == "现行"
    assert rows[1].status == "废止"
    assert rows[0].tid == "BV_GB"
    assert rows[0].effective_date == "2020-09-01"


def test_parse_search_html_nbt_47013_8() -> None:
    total, rows = parse_search_html(fixture_text("stdpage_nbt_47013_8.html"))
    assert total == 2
    assert rows[0].code == "NB/T 47013.8-2025"
    assert rows[0].status == "现行"
    assert rows[0].tid == "BV_HB"
    assert rows[1].code.startswith("NB/T 47013.8")
    assert rows[1].status == "废止"


def test_parse_detail_html_withdrawn_standard() -> None:
    detail = parse_detail_html(
        fixture_text("gb_detail_12771_2008.html"),
        tid="BV_GB",
        pid="71F772D7781BD3A7E05397BE0A0AB82A",
    )
    assert detail.code == "GB/T 12771-2008"
    assert detail.status == "废止"
    assert detail.effective_date == "2008-11-01"
    assert detail.withdrawn_on == "2020-09-01"
    assert "GB/T 12771-2000" in detail.supersedes


def test_client_verify_superseded_with_mock_transport() -> None:
    search_html = fixture_text("stdpage_gbt_12771.html")
    detail_html = fixture_text("gb_detail_12771_2008.html")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search/stdPage"):
            assert request.url.params.get("q")
            return httpx.Response(200, text=search_html)
        if request.url.path.endswith("/gb/search/gbDetailed"):
            assert request.url.params.get("id") == "71F772D7781BD3A7E05397BE0A0AB82A"
            return httpx.Response(200, text=detail_html)
        return httpx.Response(404, text="missing")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        integration = StdSamrClient(client=http_client)
        result = integration.verify("GB/T 12771-2008", review_date=date(2026, 7, 21)).to_dict()

    assert result["status"] == "COMPLETED"
    assert result["verdict"] == "superseded"
    assert result["matched"]["code"] == "GB/T 12771-2008"
    assert result["currentExecution"]["code"] == "GB/T 12771-2019"
    assert result["standardReferences"][0]["status"] == "废止"
    assert result["standardReferences"][0]["replacedBy"] == "GB/T 12771-2019"
    assert result["standardReferences"][0]["effectiveFrom"] == "2008-11-01"
    assert result["standardReferences"][0]["withdrawnOn"] == "2020-09-01"


def test_client_verify_current_with_mock_transport() -> None:
    search_html = fixture_text("stdpage_gbt_12771.html")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search/stdPage"):
            return httpx.Response(200, text=search_html)
        # Detail unavailable: verify should still use search-row status.
        return httpx.Response(404, text="missing")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        integration = StdSamrClient(client=http_client)
        result = integration.verify("GB/T 12771-2019", review_date=date(2026, 7, 21)).to_dict()

    assert result["verdict"] == "current"
    assert result["matched"]["code"] == "GB/T 12771-2019"
    assert result["standardReferences"][0]["status"] == "现行"


def test_client_rejects_unapproved_origin() -> None:
    with pytest.raises(StdSamrConfigurationError):
        StdSamrClient(origin="https://example.com")


def test_std_samr_verify_route_exposes_prefixed_contract(monkeypatch) -> None:
    expected = {
        "status": "COMPLETED",
        "citedRef": "GB/T 12771-2008",
        "canonicalRef": "GB/T 12771-2008",
        "verdict": "superseded",
        "matched": {
            "tid": "BV_GB",
            "pid": "71F772D7781BD3A7E05397BE0A0AB82A",
            "code": "GB/T 12771-2008",
            "name": "流体输送用不锈钢焊接钢管",
            "status": "废止",
            "issueDate": "2008-05-13",
            "effectiveDate": "2008-11-01",
            "detailUrl": "https://std.samr.gov.cn/gb/search/gbDetailed?id=71F772D7781BD3A7E05397BE0A0AB82A",
        },
        "currentExecution": {
            "tid": "BV_GB",
            "pid": "95A47695C5EC4F2CE05397BE0A0AB3E0",
            "code": "GB/T 12771-2019",
            "name": "流体输送用不锈钢焊接钢管",
            "status": "现行",
            "issueDate": "2019-10-18",
            "effectiveDate": "2020-09-01",
            "detailUrl": "https://std.samr.gov.cn/gb/search/gbDetailed?id=95A47695C5EC4F2CE05397BE0A0AB3E0",
        },
        "standardReferences": [
            {
                "standardRef": "GB/T 12771-2008",
                "status": "废止",
                "effectiveFrom": "2008-11-01",
                "withdrawnOn": "2020-09-01",
                "replacedBy": "GB/T 12771-2019",
            }
        ],
        "detail": None,
        "queryEndpoint": "/search/stdPage",
        "queriedAt": "2026-07-21T00:00:00Z",
    }
    monkeypatch.setattr(std_samr_routes, "query_standard_status", lambda *_a, **_k: expected)

    response = client.post(
        "/api/std-samr/standards/verify",
        json={"standardRef": "GB/T 12771-2008", "reviewDate": "2026-07-21"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"] == expected


def test_std_samr_verify_route_validates_standard_ref() -> None:
    response = client.post("/api/std-samr/standards/verify", json={"standardRef": " "})
    assert response.status_code == 200
    assert response.json()["data"]["reason"] == "VALIDATION_ERROR"


def test_std_samr_search_route_exposes_contract(monkeypatch) -> None:
    expected = {
        "status": "COMPLETED",
        "query": "GB/T 12771",
        "queryEndpoint": "/search/stdPage",
        "total": 3,
        "rows": [
            {
                "tid": "BV_GB",
                "pid": "95A47695C5EC4F2CE05397BE0A0AB3E0",
                "code": "GB/T 12771-2019",
                "name": "流体输送用不锈钢焊接钢管",
                "status": "现行",
                "issueDate": "2019-10-18",
                "effectiveDate": "2020-09-01",
                "detailUrl": "https://std.samr.gov.cn/gb/search/gbDetailed?id=95A47695C5EC4F2CE05397BE0A0AB3E0",
            }
        ],
    }
    monkeypatch.setattr(std_samr_routes, "query_standard_search", lambda *_a, **_k: expected)
    response = client.post("/api/std-samr/standards/search", json={"query": "GB/T 12771"})
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 3
