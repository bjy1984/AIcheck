"""一键分析提示词在不同模型上的离线基准（P8 H0）：同一请求发给多个模型，不落库。

用生产的 project_analysis_preview 生成真实请求，按 --nodes 取一批节点，
用生产的 validate_project_analysis_output 校验（含 quotedText 逐字核对）。
结果写到 out/<date>/pa-<project>-<model>.json 与原始输出 pa-<project>-<model>.raw.txt。

已知限制：DashScope 对 qwen-plus / qwen-flash / qwen3-30b 的 max_tokens 上限是 32768，
qwen3 开源系列非流式需要 enable_thinking=false；本脚本按模型名处理，正式链路见 P8 H1。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, os.getcwd())

from libs.db.repository import load_state, repo
from libs.db.seed import MODEL_ROUTE_VERSIONS
from libs.integrations.litellm_client import LiteLLMClient
from libs.model_usage import model_cost_cny, normalize_model_usage
from libs.project_analysis.prompt import build_batch_request, project_analysis_preview
from libs.project_analysis.validation import (
    ProjectAnalysisOutputError,
    validate_project_analysis_output,
)
from libs.qwen_runtime import QwenRuntimeClient, build_qwen_runtime_client

DEFAULT_PROJECT = "P-2026-6B15AE"
DEFAULT_NODES = "1,2,16,24"
SMALL_MODEL_MAX_TOKENS = 16384


def main() -> int:
    parser = argparse.ArgumentParser(description="一键分析多模型离线基准（不落库）")
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--nodes", default=DEFAULT_NODES, help="逗号分隔的节点 id，作为一批")
    parser.add_argument("--models", required=True, help="逗号分隔的模型名")
    parser.add_argument("--max-tokens", type=int, default=SMALL_MODEL_MAX_TOKENS)
    parser.add_argument(
        "--out", default=str(Path(__file__).resolve().parent / "out" / datetime.now(UTC).date().isoformat())
    )
    args = parser.parse_args()

    load_state()
    route = next(
        item
        for item in (repo.state.get("model_route_versions") or []) + list(MODEL_ROUTE_VERSIONS)
        if item.get("modelAlias") == "project-review-large" and item.get("status") == "production"
    )
    preview = project_analysis_preview(repo.state, args.project, model_route=route)
    batch = [int(item) for item in args.nodes.split(",") if item.strip()]
    request = build_batch_request(preview["request"], batch)
    payload = json.loads(request["messages"][1]["content"])
    present = [int(node.get("nodeId")) for node in payload.get("nodes") or [] if node.get("nodeId")]
    expected = present or batch
    print("BATCH", expected, "chars", len(request["messages"][1]["content"]), flush=True)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = build_qwen_runtime_client(LiteLLMClient)

    for model in [item.strip() for item in args.models.split(",") if item.strip()]:
        started = time.time()
        record: dict = {"model": model, "project": args.project, "nodes": expected}
        try:
            extra = {"enable_thinking": False} if model.startswith("qwen3-") else {}
            response = client.chat_sync(
                request["messages"],
                model=model,
                temperature=float(request["temperature"]),
                response_format=request["response_format"],
                max_tokens=args.max_tokens,
                timeout=1500,
                **extra,
            )
            record["elapsedSeconds"] = round(time.time() - started)
            usage = response.get("usage") or {}
            record["usage"] = normalize_model_usage(usage)
            record["costCny"] = model_cost_cny(usage)
            record["finishReason"] = (response.get("choices") or [{}])[0].get("finish_reason")
            content = QwenRuntimeClient.first_message_text(response)
            record["outputChars"] = len(content)
            (out_dir / f"pa-{args.project}-{model}.raw.txt").write_text(content, encoding="utf-8")
            try:
                validated = validate_project_analysis_output(
                    content, preview["snapshot"], payload, expected_node_ids=expected
                )
                reviews = validated.get("nodeReviews") or []
                findings = [
                    finding for review in reviews for finding in (review.get("findings") or [])
                ]
                record.update(
                    {
                        "valid": True,
                        "nodeReviews": len(reviews),
                        "findings": len(findings),
                        "findingsInvalid": sum(
                            1 for item in findings if item.get("validationFailures")
                        ),
                        "withEvidence": sum(1 for item in findings if item.get("evidenceRefs")),
                        "results": {
                            str(review.get("reviewResult") or "?"): 1 for review in reviews
                        },
                        "perNode": [
                            {
                                "nodeId": review.get("nodeId"),
                                "result": review.get("reviewResult"),
                                "findings": len(review.get("findings") or []),
                                "titles": [
                                    str(item.get("title") or "")[:60]
                                    for item in (review.get("findings") or [])
                                ],
                            }
                            for review in reviews
                        ],
                    }
                )
            except ProjectAnalysisOutputError as exc:
                record["valid"] = False
                record["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - 基准要把异常当结果记录
            record["elapsedSeconds"] = round(time.time() - started)
            record["exception"] = repr(exc)[:300]
        (out_dir / f"pa-{args.project}-{model}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
        print("RESULT", json.dumps(record, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
