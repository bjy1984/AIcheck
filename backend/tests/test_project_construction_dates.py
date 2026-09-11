"""项目施工起止日期：证书有效期覆盖判定的唯一来源，2026-09-11 前没有录入口。

全节点扫描：check_date_covers 在所有项目上都报 periodStart_and_periodEnd_missing，
生产里没有一个项目填了 constructionStart / plannedConstructionEnd——不是没人填，
是创建与更新项目的 API 根本不接这两个字段，界面上也没有地方填。
证书节点（1/2/3/24/38）的有效期覆盖因此从结构上无法判定。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.review_orchestrator.certificate_facts import project_certificate_period

client = TestClient(app)


def assert_ok(response):
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def assert_business_error(response):
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] != 0, payload
    return payload


def _create(code: str, **extra) -> dict:
    return assert_ok(
        client.post(
            "/api/projects",
            json={
                "businessPackId": "compliance_audit_v1",
                "code": code,
                "name": f"施工日期验证 {code}",
                "type": "长输压力管道",
                "region": "华东",
                "ownerOrgName": "华东管网建设公司",
                "contractorOrgName": "粤海安装工程有限公司",
                "inspectionOrgName": "省特检院一部",
                "memberUserIds": {
                    "owner": "USER-OWNER-001",
                    "contractor": "USER-CONTRACTOR-001",
                    "inspection": "USER-INSPECTION-001",
                },
                **extra,
            },
            headers={"Idempotency-Key": f"construction-dates-{code}"},
        )
    )


def test_创建时可以带施工起止日期_并能被证书期间读到():
    created = _create("P-CD-001", constructionStart="2026-03-01", plannedConstructionEnd="2026-12-31")
    project = created["project"]
    assert project["constructionStart"] == "2026-03-01"
    assert project["plannedConstructionEnd"] == "2026-12-31"
    # 证书节点的判定入口读的就是这两个键。
    period = project_certificate_period(project)
    assert str(period["periodStart"]) == "2026-03-01"
    assert str(period["periodEnd"]) == "2026-12-31"
    # 详情接口也带出来，前端编辑表单要回填。
    detail = assert_ok(client.get("/api/projects/P-CD-001"))
    assert detail["project"]["constructionStart"] == "2026-03-01"


def test_不填时是None_不是空串():
    created = _create("P-CD-002")
    assert created["project"]["constructionStart"] is None
    assert created["project"]["plannedConstructionEnd"] is None
    assert project_certificate_period(created["project"])["periodStart"] is None


def test_更新可以补填也可以清掉():
    created = _create("P-CD-003")
    etag = created["project"]["etag"]
    updated = assert_ok(
        client.put(
            "/api/projects/P-CD-003",
            json={"constructionStart": "2026-05-01", "plannedConstructionEnd": "2027-04-30"},
            headers={"If-Match": etag},
        )
    )
    assert updated["project"]["constructionStart"] == "2026-05-01"
    assert [item["field"] for item in updated["changed"]] == ["constructionStart", "plannedConstructionEnd"]

    cleared = assert_ok(
        client.put(
            "/api/projects/P-CD-003",
            json={"constructionStart": ""},
            headers={"If-Match": updated["project"]["etag"]},
        )
    )
    assert cleared["project"]["constructionStart"] is None
    assert cleared["project"]["plannedConstructionEnd"] == "2027-04-30", "没提到的字段不能被顺手清掉"


def test_写坏的日期被拒绝_不落库():
    """落一个「2028-1-17」进去，后面比对按字符串比就错了——宁可拒绝。"""
    error = assert_business_error(_create_raw("P-CD-004", constructionStart="2028-1-17"))
    assert "construction_date_invalid" in str(error)
    assert client.get("/api/projects/P-CD-004").json()["code"] != 0, "校验失败的项目不该被创建"

    created = _create("P-CD-005")
    error = assert_business_error(
        client.put(
            "/api/projects/P-CD-005",
            json={"plannedConstructionEnd": "明年年底"},
            headers={"If-Match": created["project"]["etag"]},
        )
    )
    assert "construction_date_invalid" in str(error)
    assert assert_ok(client.get("/api/projects/P-CD-005"))["project"]["plannedConstructionEnd"] is None


def test_起点晚于终点被拒绝():
    """有效期覆盖比对的是 [start, end]，倒过来的区间没有意义。"""
    error = assert_business_error(
        _create_raw("P-CD-006", constructionStart="2027-01-01", plannedConstructionEnd="2026-01-01")
    )
    assert "construction_period_inverted" in str(error)


def _create_raw(code: str, **extra):
    return client.post(
        "/api/projects",
        json={
            "businessPackId": "compliance_audit_v1",
            "code": code,
            "name": f"施工日期验证 {code}",
            "type": "长输压力管道",
            "region": "华东",
            "ownerOrgName": "华东管网建设公司",
            "contractorOrgName": "粤海安装工程有限公司",
            "inspectionOrgName": "省特检院一部",
            "memberUserIds": {
                "owner": "USER-OWNER-001",
                "contractor": "USER-CONTRACTOR-001",
                "inspection": "USER-INSPECTION-001",
            },
            **extra,
        },
        headers={"Idempotency-Key": f"construction-dates-raw-{code}"},
    )
