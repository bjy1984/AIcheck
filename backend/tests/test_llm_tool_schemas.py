from apps.api.routes import REVIEW_CONVERSATION_AGENT_TOOLS
from libs.review_orchestrator.llm_tool_schemas import (
    CONVERSATION_AGENT_RUNTIME_TOOL_NAMES,
    EXTERNAL_REGISTRY_LLM_TOOLS,
    EXTERNAL_REGISTRY_TOOL_NAMES,
    build_llm_tools_for_runtime,
    is_external_registry_tool,
    llm_tool_schema_for_runtime,
)
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool


def test_review_conversation_agent_tools_include_external_registry() -> None:
    names = {item["function"]["name"] for item in REVIEW_CONVERSATION_AGENT_TOOLS}
    assert "lookup_standard_status" in names
    assert "search_samr_standards" in names
    assert "search_cnse_organizations" in names
    assert "check_design_license_scope" in names
    assert "check_date_covers" in names
    assert "check_all_equal" in names
    assert "extract_table_records" in names
    assert "recognize_signatures_and_seals" in names
    assert "validate_evidence_grounding" in names
    assert "check_installation_license_scope" in names


def test_conversation_agent_runtime_tool_names_cover_r01_judgment_tools() -> None:
    assert "check_all_equal" in CONVERSATION_AGENT_RUNTIME_TOOL_NAMES
    assert "check_design_license_scope" in CONVERSATION_AGENT_RUNTIME_TOOL_NAMES
    assert "check_date_covers" in CONVERSATION_AGENT_RUNTIME_TOOL_NAMES
    assert "validate_evidence_grounding" in CONVERSATION_AGENT_RUNTIME_TOOL_NAMES


def test_external_registry_llm_tools_include_std_samr_and_cnse() -> None:
    names = {item["function"]["name"] for item in EXTERNAL_REGISTRY_LLM_TOOLS}
    assert names == {
        "search_cnse_organizations",
        "search_cnse_persons",
        "lookup_standard_status",
        "search_samr_standards",
    }


def test_llm_tool_schema_for_lookup_standard_status() -> None:
    schema = llm_tool_schema_for_runtime("lookup_standard_status")
    assert schema is not None
    params = schema["function"]["parameters"]
    assert params["required"] == ["standardRef"]
    assert "reviewDate" in params["properties"]


def test_build_llm_tools_for_runtime_includes_business_tools() -> None:
    tools = build_llm_tools_for_runtime(["lookup_standard_status", "check_date_covers"])
    names = {item["function"]["name"] for item in tools}
    assert names == {"lookup_standard_status", "check_date_covers"}


def test_is_external_registry_tool() -> None:
    assert is_external_registry_tool("lookup_standard_status")
    assert is_external_registry_tool("search_samr_standards")
    assert not is_external_registry_tool("extract_document_fields")
    assert EXTERNAL_REGISTRY_TOOL_NAMES == frozenset(
        {
            "search_cnse_organizations",
            "search_cnse_persons",
            "lookup_standard_status",
            "search_samr_standards",
        }
    )


def test_runtime_tool_dispatcher_searches_samr_standards(monkeypatch) -> None:
    expected = {
        "status": "COMPLETED",
        "query": "GB/T 12771",
        "total": 3,
        "rows": [{"code": "GB/T 12771-2019", "status": "现行"}],
    }
    monkeypatch.setattr(
        "libs.review_orchestrator.runtime_tools.query_standard_search",
        lambda query, page=1: expected,
    )

    result = dispatch_runtime_tool(
        {},
        "search_samr_standards",
        {"query": " GB/T 12771 ", "page": 1},
    )

    assert result["status"] == "succeeded"
    assert result["toolName"] == "search_samr_standards"
    assert result["query"] == "GB/T 12771"
    assert result["total"] == 3
    assert result["rowCount"] == 1
    assert result["requiresHumanConfirmation"] is True
