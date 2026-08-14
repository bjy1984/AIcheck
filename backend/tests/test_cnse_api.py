from __future__ import annotations

import base64
import io
import os

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from apps.api import cnse_routes
from apps.api.cnse_service import app as service_app
from apps.api.main import app
from libs.integrations.cnse_client import (
    PERSON_FIELDS,
    PERSON_SEARCH_PATH,
    CnseApiClient,
    CnseProtocolError,
    CnseRequestError,
    normalize_id_number,
)
from libs.integrations.cnse_opencv_solver import OpenCvMatch, solve_opencv_from_bytes

client = TestClient(app)

ROW = {
    "dwid": "46c6accf-684e-4d0c-bb49-a42f72fa9f1f",
    "fzjg": "新疆维吾尔自治区阿克苏地区市场监督管理局",
    "zsyxq": "2029-01-25",
    "dwmc": "新疆智仁能源有限公司拜城县察尔齐加气站",
    "dwlb": "特种设备气体充装单位",
    "sjgxsj": "2026-07-20",
    "zsyxqyz": "",
}

PERSON = {
    "ryxm": "廖柏鑫",
    "sfzh": "430524198608135291",
    "ryxb": "男",
    "zsbh": "430524198608135291",
    "zslb": "特种设备作业人员",
    "cyzl": "作业人员",
    "fzjg": "柳州市行政审批局",
    "fzjgszd": "广西",
    "khdw": "广西电力工程建设有限公司焊工考试委员会",
    "czxm": "GTAW-FeⅣ-6G-6/42-FefS-02/10/12",
    "pzrq": "2017-09-22",
    "yxrqs": "2017-09-22",
    "yxrqz": "2021-09-22",
    "yxrq": "2021-09-22 00:00:00",
    "validFlag": "1",
    "sjgxsj": "2021-05-31",
}


def png_bytes(array: np.ndarray) -> bytes:
    output = io.BytesIO()
    Image.fromarray(array, mode="RGBA").save(output, format="PNG")
    return output.getvalue()


def challenge_image(width: int, height: int, offset: int) -> bytes:
    image = np.full((height, width, 4), 255, dtype=np.uint8)
    image[offset % height, offset % width, :3] = 0
    return png_bytes(image)


def fake_solver(_puzzle: bytes, _background: bytes, *, min_confidence: float) -> OpenCvMatch:
    assert min_confidence == 0.5
    return OpenCvMatch(
        confidence=0.91,
        left=178,
        top=51,
        width=55,
        height=45,
        background_width=500,
        background_height=281,
        strategy="masked-photometric",
    )


def challenge_json() -> dict:
    return {
        "errcode": 0,
        "errmsg": "success",
        "yHeight": 51,
        "smallImage": base64.b64encode(challenge_image(55, 45, 1)).decode(),
        "bigImage": base64.b64encode(challenge_image(500, 281, 2)).decode(),
    }


def test_cnse_client_keeps_one_cookie_session_and_preserves_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"Set-Cookie": "CNSE_SESSION=test; Path=/; Secure"},
                json=challenge_json(),
            )
        assert request.headers["cookie"] == "CNSE_SESSION=test"
        assert request.content.decode() == (
            "%s&moveLength=177&pageNumber=1&pageSize=10"
            % httpx.QueryParams({"keyword": ROW["dwmc"]})
        )
        return httpx.Response(200, json={"total": 1, "rows": [ROW]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        integration = CnseApiClient(client=http_client, solver=fake_solver)
        result = integration.query(ROW["dwmc"]).to_dict()

    assert [request.method for request in requests] == ["GET", "POST"]
    assert result["status"] == "COMPLETED"
    assert result["captureMode"] == "api"
    assert result["moveLength"] == 177
    assert result["apiYHeight"] == 51
    assert result["rows"] == [ROW]


def test_cnse_person_client_keeps_session_across_challenge_check_and_query() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.endswith("pubQueryVCodeData.json"):
            return httpx.Response(
                200,
                headers={"Set-Cookie": "CNSE_SESSION=person; Path=/; Secure"},
                json=challenge_json(),
            )
        assert request.headers["cookie"] == "CNSE_SESSION=person"
        if request.method == "POST" and path.endswith("checkPubQuerycode.json"):
            assert request.content.decode() == "moveLength=177"
            return httpx.Response(200, json={"errcode": 0, "errmsg": "验证通过"})
        assert request.method == "GET"
        assert path.endswith("remotePubQuery.json")
        assert dict(request.url.params) == {
            "keyword": PERSON["sfzh"],
            "moveLength": "177",
        }
        return httpx.Response(
            200,
            json={
                "messageText": "",
                "messageLevel": "success",
                "data": {"type": "person", "data": PERSON},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        integration = CnseApiClient(client=http_client, solver=fake_solver)
        result = integration.query_person(f" {PERSON['sfzh']} ").to_dict()

    assert [request.method for request in requests] == ["GET", "POST", "GET"]
    assert result["status"] == "COMPLETED"
    assert result["idNumber"] == PERSON["sfzh"]
    assert result["queryEndpoint"] == PERSON_SEARCH_PATH
    assert result["person"] == PERSON
    assert set(result["person"]) == set(PERSON_FIELDS)


def test_cnse_person_client_rejects_non_person_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("pubQueryVCodeData.json"):
            return httpx.Response(200, json=challenge_json())
        if request.method == "POST":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "验证通过"})
        return httpx.Response(
            200,
            json={
                "messageLevel": "success",
                "data": {"type": "organization", "data": {"tyshxydm": "x"}},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        integration = CnseApiClient(client=http_client, solver=fake_solver)
        with pytest.raises(CnseProtocolError):
            integration.query_person(PERSON["sfzh"])


def test_normalize_id_number_accepts_spaced_and_lowercase_x() -> None:
    assert normalize_id_number(" 11010519491231002x ") == "11010519491231002X"


def test_cnse_backend_route_exposes_prefixed_contract(monkeypatch) -> None:
    expected = {
        "status": "COMPLETED",
        "algorithm": "opencv-edge-template-v1",
        "captureMode": "api",
        "confidence": 0.91,
        "moveLength": 177,
        "apiYHeight": 51,
        "keyword": ROW["dwmc"],
        "queryEndpoint": "/info-pub/pub/orgSearchData.json",
        "total": 1,
        "rows": [ROW],
        "targetCenter": {"x": 205, "y": 73},
        "matchBox": {"x": 178, "y": 51, "width": 55, "height": 45},
    }
    monkeypatch.setattr(cnse_routes, "query_cnse_organizations", lambda keyword: expected)

    response = client.post(
        "/api/cnse/organizations/search",
        json={"keyword": "新疆 智仁能源有限公司拜城县察尔齐加气站"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"] == expected
    assert payload["operationId"].startswith("OP-")


def test_cnse_person_route_exposes_prefixed_contract(monkeypatch) -> None:
    expected = {
        "status": "COMPLETED",
        "algorithm": "opencv-edge-template-v1",
        "captureMode": "api",
        "confidence": 0.91,
        "moveLength": 177,
        "apiYHeight": 51,
        "idNumber": PERSON["sfzh"],
        "queryEndpoint": PERSON_SEARCH_PATH,
        "person": PERSON,
        "targetCenter": {"x": 205, "y": 73},
        "matchBox": {"x": 178, "y": 51, "width": 55, "height": 45},
    }
    monkeypatch.setattr(cnse_routes, "query_cnse_persons", lambda id_number: expected)

    response = client.post(
        "/api/cnse/persons/search",
        json={"idNumber": f" {PERSON['sfzh']} "},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"] == expected
    assert payload["operationId"].startswith("OP-")


def test_cnse_backend_route_validates_input_without_calling_upstream(monkeypatch) -> None:
    called = False

    def should_not_run(_keyword: str) -> dict:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(cnse_routes, "query_cnse_organizations", should_not_run)

    response = client.post("/api/cnse/organizations/search", json={"keyword": " "})

    assert response.status_code == 200
    assert response.json()["data"]["reason"] == "VALIDATION_ERROR"
    assert called is False


def test_cnse_person_route_validates_input_without_calling_upstream(monkeypatch) -> None:
    called = False

    def should_not_run(_id_number: str) -> dict:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(cnse_routes, "query_cnse_persons", should_not_run)

    response = client.post("/api/cnse/persons/search", json={"idNumber": "123"})

    assert response.status_code == 200
    assert response.json()["data"]["reason"] == "VALIDATION_ERROR"
    assert called is False


def test_cnse_backend_route_maps_upstream_failure(monkeypatch) -> None:
    def fail_query(_keyword: str) -> dict:
        raise CnseRequestError("sensitive upstream detail")

    monkeypatch.setattr(cnse_routes, "query_cnse_organizations", fail_query)

    response = client.post("/api/cnse/organizations/search", json={"keyword": "测试单位"})

    assert response.status_code == 502
    payload = response.json()
    assert payload["data"]["reason"] == "CNSE_UPSTREAM_FAILED"
    assert "sensitive" not in str(payload)


def test_cnse_person_route_maps_upstream_failure(monkeypatch) -> None:
    def fail_query(_id_number: str) -> dict:
        raise CnseRequestError("sensitive upstream detail")

    monkeypatch.setattr(cnse_routes, "query_cnse_persons", fail_query)

    response = client.post(
        "/api/cnse/persons/search",
        json={"idNumber": PERSON["sfzh"]},
    )

    assert response.status_code == 502
    payload = response.json()
    assert payload["data"]["reason"] == "CNSE_UPSTREAM_FAILED"
    assert "sensitive" not in str(payload)


def test_cnse_route_remains_protected_when_auth_is_required(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")

    response = client.post("/api/cnse/organizations/search", json={"keyword": "测试单位"})

    assert response.json()["data"]["reason"] == "AUTH_REQUIRED"


def test_cnse_route_is_published_in_openapi() -> None:
    schema = app.openapi()

    org_operation = schema["paths"]["/api/cnse/organizations/search"]["post"]
    person_operation = schema["paths"]["/api/cnse/persons/search"]["post"]
    assert org_operation["requestBody"]["required"] is True
    assert person_operation["requestBody"]["required"] is True
    assert org_operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert person_operation["responses"]["200"]["content"]["application/json"]["schema"]


def test_ported_opencv_solver_matches_masked_photometric_coordinates() -> None:
    rng = np.random.default_rng(42)
    background = np.full((80, 140, 4), 255, dtype=np.uint8)
    background[:, :, :3] = rng.integers(30, 225, size=(80, 140, 3), dtype=np.uint8)
    left, top = 73, 29
    puzzle = background[top : top + 25, left : left + 31].copy()
    puzzle[:, :, 3] = 0
    puzzle[3:-3, 3:-3, 3] = 255

    result = solve_opencv_from_bytes(png_bytes(puzzle), png_bytes(background))

    assert (result.left, result.top) == (left, top)
    assert result.strategy == "masked-photometric"


def test_dedicated_cnse_service_requires_api_key(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_CNSE_API_KEY", "test-cnse-api-key-with-at-least-32-bytes")
    monkeypatch.setattr(cnse_routes, "query_cnse_organizations", lambda keyword: {})
    monkeypatch.setattr(cnse_routes, "query_cnse_persons", lambda id_number: {})

    with TestClient(service_app) as dedicated_client:
        health = dedicated_client.get("/api/healthz")
        unauthorized_org = dedicated_client.post(
            "/api/cnse/organizations/search",
            json={"keyword": "测试单位"},
        )
        unauthorized_person = dedicated_client.post(
            "/api/cnse/persons/search",
            json={"idNumber": PERSON["sfzh"]},
        )

    assert health.status_code == 200
    assert health.json()["data"]["service"] == "aicheck-cnse-api"
    assert unauthorized_org.status_code == 401
    assert unauthorized_person.status_code == 401


@pytest.mark.skipif(
    os.getenv("AICHECK_CNSE_LIVE") != "1",
    reason="Set AICHECK_CNSE_LIVE=1 to hit the real CNSE person registry.",
)
def test_cnse_person_live_smoke_for_welder_certificate() -> None:
    with CnseApiClient(min_confidence=0.45) as integration:
        result = integration.query_person("430524198608135291").to_dict()

    assert result["status"] == "COMPLETED"
    assert result["person"]["sfzh"] == "430524198608135291"
    assert result["person"]["ryxm"] == "廖柏鑫"
