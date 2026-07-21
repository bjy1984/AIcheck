"""OpenAI-compatible function schemas for external registry runtime tools."""

from __future__ import annotations

from typing import Any


EXTERNAL_REGISTRY_TOOL_NAMES = frozenset(
    {
        "search_cnse_organizations",
        "search_cnse_persons",
        "lookup_standard_status",
        "search_samr_standards",
    }
)


def llm_function_tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


CNSE_LLM_TOOLS: list[dict[str, Any]] = [
    llm_function_tool(
        "search_cnse_organizations",
        (
            "查询全国特种设备公示信息平台的单位许可信息。"
            "输入单位名称，返回公示登记记录；不得仅凭 OCR 结果宣称已完成官网核验。"
        ),
        {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "单位名称，例如制造单位、施工单位或许可证上的单位名称。",
                }
            },
            "required": ["keyword"],
            "additionalProperties": False,
        },
    ),
    llm_function_tool(
        "search_cnse_persons",
        (
            "查询全国特种设备公示信息平台的从业人员资格信息。"
            "输入身份证号，返回焊工等作业人员公示记录；不得仅凭 OCR 结果宣称已完成官网核验。"
        ),
        {
            "type": "object",
            "properties": {
                "idNumber": {
                    "type": "string",
                    "description": "从业人员身份证号，通常来自焊工证或人员证书 OCR 结果。",
                }
            },
            "required": ["idNumber"],
            "additionalProperties": False,
        },
    ),
]


STD_SAMR_LLM_TOOLS: list[dict[str, Any]] = [
    llm_function_tool(
        "lookup_standard_status",
        (
            "查询全国标准信息公共服务平台（std.samr.gov.cn）的标准版本状态、"
            "实施日期、废止日期和替代关系。用于核验设计文件等引用的标准是否现行有效；"
            "不得仅凭本地知识库宣称已完成官方查新。"
        ),
        {
            "type": "object",
            "properties": {
                "standardRef": {
                    "type": "string",
                    "description": "标准编号，例如 GB/T 12771-2008 或 NB/T 47013.8-2012。",
                },
                "reviewDate": {
                    "type": "string",
                    "description": "审查基准日 YYYY-MM-DD；缺省按当天判断是否已实施。",
                },
            },
            "required": ["standardRef"],
            "additionalProperties": False,
        },
    ),
    llm_function_tool(
        "search_samr_standards",
        (
            "在全国标准信息公共服务平台（std.samr.gov.cn）按关键词检索标准条目，"
            "返回标准号、名称、状态、发布/实施日期和详情链接。"
            "适合先模糊搜索再调用 lookup_standard_status 做版本核验。"
        ),
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索关键词，例如 GB/T 12771、NB/T 47013.8 或标准名称片段。",
                },
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "结果页码，默认 1。",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
]


EXTERNAL_REGISTRY_LLM_TOOLS: list[dict[str, Any]] = CNSE_LLM_TOOLS + STD_SAMR_LLM_TOOLS

_LLM_TOOL_BY_NAME: dict[str, dict[str, Any]] = {
    item["function"]["name"]: item for item in EXTERNAL_REGISTRY_LLM_TOOLS
}


def is_external_registry_tool(tool_name: str) -> bool:
    return tool_name in EXTERNAL_REGISTRY_TOOL_NAMES


def llm_tool_schema_for_runtime(tool_name: str) -> dict[str, Any] | None:
    """Return an OpenAI function tool schema for a known runtime tool name."""

    explicit = _LLM_TOOL_BY_NAME.get(tool_name)
    if explicit is not None:
        return explicit

    from libs.review_orchestrator.runtime_tools import runtime_tool_catalog

    catalog = {item["name"]: item for item in runtime_tool_catalog()}
    descriptor = catalog.get(tool_name)
    if descriptor is None:
        return None

    if tool_name == "locate_evidence_fragment":
        parameters = {
            "type": "object",
            "properties": {
                "documentVersionIds": {"type": "array", "items": {"type": "string"}},
                "queryTerms": {"type": "array", "items": {"type": "string"}},
                "minConfidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["queryTerms"],
            "additionalProperties": False,
        }
    elif tool_name == "extract_document_fields":
        parameters = {
            "type": "object",
            "properties": {
                "documentVersionIds": {"type": "array", "items": {"type": "string"}},
                "fieldCodes": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        }
    elif tool_name == "extract_table_records":
        parameters = {
            "type": "object",
            "properties": {
                "documentVersionIds": {"type": "array", "items": {"type": "string"}},
                "businessSchemas": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        }
    elif tool_name in {
        "get_document_ocr_result",
        "recognize_document_seals",
        "recognize_signatures_and_seals",
        "extract_structured_fields",
        "extract_welder_certificate",
        "verify_license_or_certificate",
        "verify_welder_certificate_authenticity",
    }:
        parameters = {
            "type": "object",
            "properties": {
                "documentVersionIds": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        }
    else:
        parameters = {"type": "object", "properties": {}, "additionalProperties": False}

    return llm_function_tool(
        tool_name,
        str(descriptor.get("capability") or "执行审查辅助工具。"),
        parameters,
    )


def build_llm_tools_for_runtime(tool_names: list[str]) -> list[dict[str, Any]]:
    """Build OpenAI tool definitions for the given runtime tool names."""

    tools: list[dict[str, Any]] = []
    for name in tool_names:
        schema = llm_tool_schema_for_runtime(name)
        if schema is not None:
            tools.append(schema)
    return tools
