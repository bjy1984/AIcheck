from __future__ import annotations

from libs.raw_vault import InMemoryRawVaultStore, RawCapture, RawCaptureContext
from libs.review_tools import execute_node_tool_plan


def test_common_tool_executor_archives_complete_request_and_result() -> None:
    store = InMemoryRawVaultStore()
    capture = RawCapture(store=store)
    context = RawCaptureContext("TENANT-A", "RRUN-TOOLS", review_run_id="RRUN-TOOLS")
    plan = [
        {
            "atomicCheckId": "A1",
            "compilable": True,
            "tools": ["check"],
            "parameters": {},
            "requiredFacts": [],
        }
    ]

    execute_node_tool_plan(
        plan,
        tool_runner=lambda _name, args: {"status": "passed", "arguments": args, "unabridged": "完整结果"},
        tool_arguments={"check": {"nodeId": 12}},
        raw_capture=capture,
        raw_context=context,
        turn=2,
    )

    events = store.events_for_run("TENANT-A", "RRUN-TOOLS")
    assert [event.event_type for event in events] == [
        "tool.call.requested",
        "tool.call.completed",
    ]
    assert b'"nodeId":12' in (store.payload_for(events[0].id) or b"")
    assert b"unabridged" in (store.payload_for(events[1].id) or b"")
    assert events[0].provider_tool_call_id == events[1].provider_tool_call_id


def test_tool_exception_is_archived_then_re_raised() -> None:
    store = InMemoryRawVaultStore()
    capture = RawCapture(store=store)
    context = RawCaptureContext("TENANT-A", "RRUN-TOOLS")

    def fail(_name, _arguments):
        raise ValueError("bad input")

    try:
        execute_node_tool_plan(
            [{"atomicCheckId": "A1", "compilable": True, "tools": ["check"], "parameters": {}}],
            tool_runner=fail,
            raw_capture=capture,
            raw_context=context,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("tool exception was swallowed")

    event = store.events_for_run("TENANT-A", "RRUN-TOOLS")[-1]
    assert event.event_type == "tool.call.failed"
    assert b"ValueError" in (store.payload_for(event.id) or b"")
