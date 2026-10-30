"""R08 在线核验标准：时间线没收录、带年份的引用逐个查官网，查到废止就判不符合。

ECD202 储罐 8：65 条引用里 58 条「未收录」，绑定里的 lookup_standard_status 调用时不带标准号，
一律 VALIDATION_ERROR，GB/T 12771-2008 等早已废止的版本一直没被核出来。"""
from __future__ import annotations

import pytest

from libs import standard_online_lookup as online
from libs.business_pack import load_business_pack
from libs.integrations.std_samr_client import StdSamrConfigurationError, StdSamrRequestError
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan
from libs.review_tools.business_tools import check_standard_version_active, with_online_statuses


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    online.clear_cache()
    monkeypatch.delenv(online.ENABLE_ENV, raising=False)
    yield
    online.clear_cache()


def verdict(kind: str, code: str, *, effective="2010-01-01", withdrawn=None, replaced=None) -> dict:
    return {"verdict": kind, "reviewDate": "2026-03-25",
            "standardReferences": [{"standardRef": code, "status": "废止" if kind == "superseded" else "现行",
                                    "effectiveFrom": effective, "withdrawnOn": withdrawn, "replacedBy": replaced}]}


def fake_query(table: dict, calls: list | None = None):
    def query(ref, review_date=None):
        if calls is not None:
            calls.append(ref)
        value = table[ref]
        if isinstance(value, Exception):
            raise value
        return value
    return query


def test_resolves_withdrawn_and_current_and_skips_what_cannot_be_judged():
    calls: list[str] = []
    table = {"GB/T 12771-2008": verdict("superseded", "GB/T 12771-2008", effective="2009-04-01", withdrawn="2020-09-01", replaced="GB/T 12771-2019"),
             "GB/T 8163-2018": verdict("current", "GB/T 8163-2018")}
    out = online.lookup_standard_statuses(
        ["GB/T 12771-2008", "GB/T 12771-2008", "GB/T 20801.1", "不是编号", "GB/T 8163-2018"], "2026-03-25",
        query=fake_query(table, calls), sleep=lambda _: None)
    assert calls == ["GB/T 12771-2008", "GB/T 8163-2018"], "重复的只查一次，没有年份的不查"
    by_ref = {item["standardRef"]: item for item in out["lookups"]}
    assert by_ref["GB/T 12771-2008"]["verdict"] == "superseded" and by_ref["GB/T 12771-2008"]["withdrawnOn"] == "2020-09-01"
    assert by_ref["GB/T 12771-2008"]["replacedBy"] == "GB/T 12771-2019" and by_ref["GB/T 12771-2008"]["source"] == "std.samr.gov.cn"
    assert {item["standardRef"]: item["reason"] for item in out["skipped"]} == {"GB/T 20801.1": "no_year", "不是编号": "invalid_ref"}
    assert out["unresolved"] == []


def test_ambiguous_and_not_found_stay_unresolved_instead_of_guessing():
    table = {"HG/T 20592-2009": {"verdict": "not_found", "standardReferences": []},
             "GB 50316-2000": {"verdict": "ambiguous", "standardReferences": []}}
    out = online.lookup_standard_statuses(["HG/T 20592-2009", "GB 50316-2000"], "2026-03-25", query=fake_query(table), sleep=lambda _: None)
    assert out["lookups"] == []
    assert {item["standardRef"]: item["reason"] for item in out["unresolved"]} == {"HG/T 20592-2009": "not_found", "GB 50316-2000": "ambiguous"}


def test_stops_after_three_consecutive_upstream_failures_and_marks_the_rest():
    refs = [f"GB/T 1000{i}-2010" for i in range(6)]
    table = {ref: StdSamrRequestError("boom") for ref in refs}
    calls: list[str] = []
    out = online.lookup_standard_statuses(refs, "2026-03-25", query=fake_query(table, calls), sleep=lambda _: None)
    assert len(calls) == 3, "连续失败三次就停，不再打上游"
    assert [item["reason"] for item in out["unresolved"]] == ["upstream_failed"] * 3 + ["not_queried_after_repeated_failures"] * 3


def test_a_success_resets_the_failure_count():
    refs = ["GB/T 10001-2010", "GB/T 10002-2010", "GB/T 10003-2010", "GB/T 10004-2010", "GB/T 10005-2010"]
    table = {refs[0]: StdSamrRequestError("x"), refs[1]: StdSamrRequestError("x"), refs[2]: verdict("current", refs[2]),
             refs[3]: StdSamrRequestError("x"), refs[4]: verdict("current", refs[4])}
    out = online.lookup_standard_statuses(refs, "2026-03-25", query=fake_query(table), sleep=lambda _: None)
    assert [item["standardRef"] for item in out["lookups"]] == [refs[2], refs[4]]


def test_misconfigured_upstream_stops_everything():
    table = {"GB/T 10001-2010": StdSamrConfigurationError("bad origin"), "GB/T 10002-2010": verdict("current", "GB/T 10002-2010")}
    calls: list[str] = []
    out = online.lookup_standard_statuses(list(table), "2026-03-25", query=fake_query(table, calls), sleep=lambda _: None)
    assert calls == ["GB/T 10001-2010"] and out["lookups"] == []
    assert [item["reason"] for item in out["unresolved"]] == ["misconfigured", "misconfigured"]


def test_deadline_and_limit_bound_the_work(monkeypatch):
    refs = [f"GB/T 2{i:04d}-2010" for i in range(5)]
    table = {ref: verdict("current", ref) for ref in refs}
    clock = iter([0.0, 0.0, 0.0, 999.0, 999.0, 999.0, 999.0, 999.0, 999.0, 999.0, 999.0, 999.0])
    out = online.lookup_standard_statuses(refs, "2026-03-25", query=fake_query(table), sleep=lambda _: None, monotonic=lambda: next(clock))
    assert len(out["lookups"]) == 1
    assert {item["reason"] for item in out["unresolved"]} == {"deadline_exceeded"}

    monkeypatch.setattr(online, "MAX_REFERENCES", 2)
    online.clear_cache()
    limited = online.lookup_standard_statuses(refs, "2026-03-25", query=fake_query(table), sleep=lambda _: None)
    assert len(limited["lookups"]) == 2 and {item["reason"] for item in limited["unresolved"]} == {"over_limit"}


def test_results_are_cached_per_review_date():
    calls: list[str] = []
    table = {"GB/T 8163-2018": verdict("current", "GB/T 8163-2018")}
    for _ in range(2):
        online.lookup_standard_statuses(["GB/T 8163-2018"], "2026-03-25", query=fake_query(table, calls), sleep=lambda _: None)
    assert calls == ["GB/T 8163-2018"]
    online.lookup_standard_statuses(["GB/T 8163-2018"], "2026-10-29", query=fake_query(table, calls), sleep=lambda _: None)
    assert len(calls) == 2, "审查日不同，答案可能不同，不能共用缓存"


def reference(code: str, status: str = "unknown") -> dict:
    return {"standardRef": code, "status": status, "effectiveFrom": None, "withdrawnOn": None,
            "timelineStatus": status, "verified": False, "requiresOnlineLookup": status == "unknown"}


def test_online_withdrawn_standard_fails_the_version_check_and_current_one_passes():
    refs = [reference("GB/T 12771-2008"), reference("GB/T 8163-2018")]
    online_rows = [{"standardRef": "GB/T 12771-2008", "verdict": "superseded", "effectiveFrom": "2009-04-01", "withdrawnOn": "2020-09-01",
                    "replacedBy": "GB/T 12771-2019", "source": "std.samr.gov.cn"},
                   {"standardRef": "GB/T 8163-2018", "verdict": "current", "effectiveFrom": "2019-02-01", "withdrawnOn": None}]
    outcome = check_standard_version_active({"standardReferences": refs, "reviewDate": "2026-03-25", "onlineStatuses": online_rows})
    assert outcome["result"] == "failed"
    failed = [item for item in outcome["checks"] if not item["passed"]]
    assert [item["code"] for item in failed] == ["GB/T 12771-2008"]
    assert failed[0]["actual"]["replacedBy"] == "GB/T 12771-2019" and failed[0]["actual"]["statusSource"] == "std.samr.gov.cn"

    only_current = check_standard_version_active({"standardReferences": [refs[1]], "reviewDate": "2026-03-25", "onlineStatuses": online_rows})
    assert only_current["result"] == "passed"


def test_online_not_yet_effective_standard_goes_to_a_human_not_to_failed():
    rows = [{"standardRef": "GB/T 99999-2030", "verdict": "not_yet_effective", "effectiveFrom": "2030-01-01"}]
    outcome = check_standard_version_active({"standardReferences": [reference("GB/T 99999-2030")], "reviewDate": "2026-03-25", "onlineStatuses": rows})
    assert outcome["result"] == "human_review_required"


def test_online_status_never_overrides_the_local_timeline():
    local = reference("TSG D0001-2009", "withdrawn")
    merged = with_online_statuses([local], [{"standardRef": "TSG D0001-2009", "verdict": "current", "source": "std.samr.gov.cn"}])
    assert merged == [local]


def test_references_without_online_data_are_left_exactly_as_before():
    refs = [reference("GB/T 12459-2017")]
    assert with_online_statuses(refs, []) == refs
    assert with_online_statuses(refs, [{"standardRef": "GB/T 12459-2017", "verdict": "ambiguous"}]) == refs


def test_lookup_tool_in_plan_mode_is_off_by_default_and_never_calls_the_platform(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("不该对外发请求")
    monkeypatch.setattr(online, "query_standard_status", boom)
    out = dispatch_runtime_tool({}, "lookup_standard_status", {"standardRefs": ["GB/T 12771-2008"], "reviewDate": "2026-03-25"})
    assert out["status"] == "succeeded" and out["lookups"] == []
    assert out["skipped"] == [{"standardRef": "GB/T 12771-2008", "reason": "online_lookup_disabled"}]
    assert "result" not in out, "它只补事实，不投票"


def test_lookup_tool_without_any_standard_still_rejects_single_mode():
    out = dispatch_runtime_tool({}, "lookup_standard_status", {})
    assert out["status"] == "failed" and out["errorCode"] == "VALIDATION_ERROR"


def test_r08_plan_runs_the_lookup_and_the_withdrawn_standard_reaches_the_version_check(monkeypatch):
    monkeypatch.setenv(online.ENABLE_ENV, "1")
    table = {"GB/T 12771-2008": verdict("superseded", "GB/T 12771-2008", effective="2009-04-01", withdrawn="2020-09-01")}
    monkeypatch.setattr(online, "query_standard_status", fake_query(table))
    monkeypatch.setattr(online, "INTERVAL_SECONDS", 0)
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = [item for item in compile_node_tool_plan(pack, "R08", available_tools=available) if item["atomicCheckId"] == "AC-R08-01"]
    assert "lookup_standard_status" in plan[0]["tools"]
    facts = {"design": {"reviewDate": "2026-03-25", "standardReferences": [reference("GB/T 12771-2008"), reference("GB/T 20801.1", "unknown")]},
             "project": {"constructionStart": "2026-03-25"}}
    calls: list[tuple[str, dict]] = []

    def runner(name: str, arguments: dict) -> dict:
        calls.append((name, arguments))
        return dispatch_runtime_tool({}, name, arguments)

    output = execute_node_tool_plan(plan, facts=facts, tool_runner=runner, document_version_ids=[])
    lookup_args = next(args for name, args in calls if name == "lookup_standard_status")
    assert lookup_args["standardRefs"] == ["GB/T 12771-2008", "GB/T 20801.1"]
    version_args = next(args for name, args in calls if name == "check_standard_version_active")
    assert [row["standardRef"] for row in version_args["onlineStatuses"]] == ["GB/T 12771-2008"]
    version_output = next(item for item in output["atomicResults"][0]["toolResults"] if item.get("toolName") == "check_standard_version_active")
    assert version_output["result"] == "failed"
    lookup_output = next(item for item in output["atomicResults"][0]["toolResults"] if item.get("toolName") == "lookup_standard_status")
    assert lookup_output["status"] == "succeeded", "不再是 VALIDATION_ERROR"
