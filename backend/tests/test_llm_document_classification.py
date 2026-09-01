from __future__ import annotations

import json

import pytest


class FakeClassificationClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def chat_sync(self, messages: list[dict], model: str, **kwargs: object) -> dict:
        self.calls.append({"messages": messages, "model": model, "kwargs": kwargs})
        return {
            "id": "chatcmpl-classifier-1",
            "model": "qwen3.8-max",
            "provider": "Model Studio / DashScope",
            "choices": [
                {
                    "message": {"content": json.dumps(self.payload, ensure_ascii=False)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }


def test_llm_classifier_returns_existing_single_type_with_grounded_evidence() -> None:
    from libs.llm_document_classification import classify_document_text

    ocr_text = "特种设备设计许可证\n许可项目：压力管道设计\n有效期至2030年"
    client = FakeClassificationClient(
        {
            "materialTypeCode": "design_license",
            "confidence": 0.97,
            "reason": "正文明确为压力管道设计许可证",
            "contentEvidence": ["许可项目：压力管道设计"],
        }
    )

    classification, audit = classify_document_text(client, ocr_text)

    assert classification == {
        "materialCategory": "资质证照",
        "materialTypeCode": "design_license",
        "materialTypeName": "设计单位许可证",
        "matchedBy": "llm",
        "reason": "正文明确为压力管道设计许可证",
        "classificationStatus": "classified",
        "classificationConfidence": 0.97,
        "classificationSource": "llm_classifier",
        "classificationReasons": ["正文明确为压力管道设计许可证", "原文证据：许可项目：压力管道设计"],
        "classifierVersion": "llm-material-classifier-v1",
    }
    assert audit["providerRequestId"] == "chatcmpl-classifier-1"
    assert audit["usage"]["total_tokens"] == 120
    assert client.calls[0]["model"] == "document-classifier"
    rendered_prompt = "\n".join(str(message.get("content") or "") for message in client.calls[0]["messages"])
    assert "json" in rendered_prompt.lower()


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        (
            {
                "materialTypeCode": "invented_type",
                "confidence": 0.9,
                "reason": "猜测",
                "contentEvidence": ["许可项目：压力管道设计"],
            },
            "UNKNOWN_MATERIAL_TYPE",
        ),
        (
            {
                "materialTypeCode": "design_license",
                "confidence": 0.9,
                "reason": "猜测",
                "contentEvidence": ["原文中根本不存在的许可证范围"],
            },
            "UNGROUNDED_CLASSIFICATION_EVIDENCE",
        ),
        (
            {
                "materialTypeCode": "design_license",
                "confidence": 0.9,
                "reason": "格式错误",
                "contentEvidence": "许可项目：压力管道设计",
            },
            "INVALID_CLASSIFICATION_EVIDENCE",
        ),
        (
            {
                "materialTypeCode": "design_license",
                "confidence": 0.9,
                "reason": "引用没有实质内容",
                "contentEvidence": ["1"],
            },
            "CLASSIFICATION_EVIDENCE_TOO_WEAK",
        ),
    ],
)
def test_llm_classifier_rejects_unknown_type_or_ungrounded_evidence(
    payload: dict,
    error_code: str,
) -> None:
    from libs.llm_document_classification import LlmClassificationError, classify_document_text

    client = FakeClassificationClient(payload)

    with pytest.raises(LlmClassificationError, match=error_code):
        classify_document_text(client, "第1页 许可项目：压力管道设计")
