"""节点级 AI 审查在不同模型 / 不同资产版本上的离线基准（P8 H0）。

做法：克隆一条已完成的 ai_run，用生产的 attach_review_evidence_package_to_ai_run 重建证据分片，
走完整的 execute_review_run_inline（规则引擎、提示词、模型、接地守卫、质量门），
只把所有落库函数换成空操作。结果写到 out/<date>/review-<model>-<project>-<node>.json。

两处坑（2026-09-06 实测，改脚本前先读）：
1. 克隆会继承 evidenceManifestId / evidenceShardIds，已 completed 的分片会直接复用旧草稿，
   零模型调用还看起来"跑完了"。必须重建证据包并把分片置回 pending。
2. create_review_run_from_ai_run 不重建分片；没有证据包时整份资料进一次调用
   （节点 2 实测 124k token），与生产分片行为不一致。

只在生产容器里手动跑，不进 cron：
  docker exec -w /app -e PYTHONPATH=/app -e AICHECK_LLM_MODEL_REVIEW=<model> aicheck-api \\
      python3 scripts/experiments/review_model_compare.py --project P-2026-6B15AE --node 24
每轮六模型约 ¥10（按系统单价折算）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

sys.path.insert(0, os.getcwd())

from libs.contracts.responses import server_time
from libs.db import repository
from libs.db.repository import load_state, repo
from libs.review_evidence import attach_review_evidence_package_to_ai_run
from libs.review_orchestrator import dispatcher, execution, persistence_retry

TEMPLATE_TITLE = "证据不足，需人工确认"
TEMPLATE_DESCRIPTION_PREFIX = "模型给出的业务结论缺少证据支持"
DEFAULT_SAMPLES = (("P-2026-6B15AE", 24), ("P-2026-ECD202", 2))
CLONE_DROP_KEYS = (
    "reviewRunId",
    "findings",
    "suggestion",
    "finishedAt",
    "toolExecutions",
    "certificateVerification",
    "outputText",
    "errorCode",
    "failure",
    "findingDrafts",
    "llmMetadata",
    "promptAudit",
    "nodeFindingAggregate",
    "qualityGate",
    "modelCallAttemptIds",
    "ruleResults",
    "llmResultText",
    "reasoningProcess",
    "llmConversationId",
    "evidenceManifestId",
    "evidenceManifestHash",
    "evidenceShardIds",
    "evidenceSnapshotId",
    "evidenceSnapshotHash",
    "evidenceCoverage",
    "inputHash",
    "outputHash",
    "steps",
    "graphExecution",
    "stateTransition",
)


def disable_persistence() -> None:
    def noop(*_args, **_kwargs):
        return None

    repository.flush_state = noop
    repository.flush_state_records = noop
    for module in (execution, dispatcher, persistence_retry):
        for name in (
            "flush_state",
            "flush_state_records",
            "flush_review_run_records_with_conflict_retry",
        ):
            if hasattr(module, name):
                setattr(module, name, noop)


def latest_completed_run(project_id: str, node_id: int) -> dict | None:
    runs = [
        item
        for item in repo.state.get("ai_runs") or []
        if item.get("projectId") == project_id
        and int(item.get("nodeId") or 0) == node_id
        and item.get("status") == "完成"
        and item.get("reviewRunId")
    ]
    runs.sort(key=lambda item: str(item.get("finishedAt") or ""), reverse=True)
    return runs[0] if runs else None


def clone_run(source: dict) -> dict:
    ai_run = deepcopy(source)
    ai_run["id"] = f"AIRUN-{int(source.get('nodeId') or 0)}-EXP{uuid.uuid4().hex[:6].upper()}"
    for key in CLONE_DROP_KEYS:
        ai_run.pop(key, None)
    ai_run["status"] = "推理中"
    ai_run["startedAt"] = server_time()
    ai_run["reviewMode"] = source.get("reviewMode") or "gap_precheck"
    repo.state["ai_runs"].insert(0, ai_run)
    attach_review_evidence_package_to_ai_run(
        repo.state,
        ai_run,
        clause_package_snapshot=source.get("clausePackageSnapshot"),
        orchestration_metadata={"triggerType": "manual_node"},
    )
    for shard in repo.state.get("evidence_shards") or []:
        if str(shard.get("evidenceManifestId")) == str(ai_run.get("evidenceManifestId")):
            shard["status"] = "pending"
            for key in (
                "findingDrafts",
                "modelAttemptIds",
                "completedAt",
                "startedAt",
                "failureReason",
                "processedInputHash",
            ):
                shard.pop(key, None)
    return ai_run


def finding_metrics(drafts: list[dict]) -> dict:
    titles = [str(item.get("title") or "") for item in drafts]
    descriptions = [str(item.get("description") or "") for item in drafts]
    lengths = [len(text) for text in descriptions]
    return {
        "findings": len(drafts),
        "grounded": sum(1 for item in drafts if item.get("groundingStatus") == "grounded"),
        "withRefs": sum(1 for item in drafts if item.get("evidenceRefs")),
        "templateTitles": sum(1 for title in titles if title.startswith(TEMPLATE_TITLE)),
        "templateDescriptions": sum(
            1 for text in descriptions if text.startswith(TEMPLATE_DESCRIPTION_PREFIX)
        ),
        "duplicateTitles": len(titles) - len(set(titles)),
        "descriptionMedianChars": int(median(lengths)) if lengths else 0,
        "descriptionMaxChars": max(lengths) if lengths else 0,
        "descriptionOver150": sum(1 for length in lengths if length > 150),
        "groundedTitles": [
            title[:40]
            for title, item in zip(titles, drafts, strict=False)
            if item.get("groundingStatus") == "grounded"
        ][:8],
    }


def run_one(project_id: str, node_id: int, model_label: str, out_dir: Path) -> dict:
    source = latest_completed_run(project_id, node_id)
    if source is None:
        return {
            "model": model_label,
            "project": project_id,
            "node": node_id,
            "error": "no completed ai_run",
        }
    ai_run = clone_run(source)
    review_run = execution.create_review_run_from_ai_run(ai_run, mode="inline")
    if review_run not in (repo.state.get("review_runs") or []):
        repo.state.setdefault("review_runs", []).insert(0, review_run)
    run_id = review_run["reviewRunId"]
    record = {
        "model": model_label,
        "project": project_id,
        "node": node_id,
        "sourceAiRun": source["id"],
        "reviewRunId": run_id,
    }
    started = time.time()
    try:
        record["status"] = (execution.execute_review_run_inline(run_id) or {}).get("status")
    except Exception as exc:  # noqa: BLE001 - 基准要把异常当结果记录
        record["exception"] = repr(exc)[:300]
    record["elapsedSeconds"] = round(time.time() - started)
    stored = repo.find_one("review_runs", run_id, id_field="reviewRunId") or {}
    drafts = stored.get("findingDrafts") or []
    record.update(finding_metrics(drafts))
    attempts = [
        item
        for item in repo.state.get("model_call_attempts") or []
        if item.get("reviewRunId") == run_id
    ]
    shards = [
        item
        for item in repo.state.get("evidence_shards") or []
        if str(item.get("reviewRunId")) == run_id
    ]
    record.update(
        {
            "llmCalls": len(attempts),
            "llmFailed": sum(1 for item in attempts if item.get("status") != "success"),
            "envelopeErrors": sum(
                1
                for item in attempts
                if "ENVELOPE" in str(item.get("errorMessage") or item.get("failureReason") or "")
            ),
            "failedShards": sum(1 for item in shards if item.get("status") == "failed"),
            "shardCount": len(shards),
            "inputTokens": sum(
                int((item.get("usageNormalized") or {}).get("inputTokens") or 0)
                for item in attempts
            ),
            "outputTokens": sum(
                int((item.get("usageNormalized") or {}).get("outputTokens") or 0)
                for item in attempts
            ),
            "costCny": round(
                sum(
                    float((item.get("costNormalized") or {}).get("total") or 0) for item in attempts
                ),
                4,
            ),
            "opinionDraftIsTemplate": str(
                (ai_run.get("suggestion") or {}).get("opinionDraft") or ""
            ).startswith(TEMPLATE_DESCRIPTION_PREFIX),
            "errorCode": stored.get("errorCode"),
            "errorMessage": str(stored.get("errorMessage") or "")[:300],
        }
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"review-{model_label}-{project_id}-{node_id}.json").write_text(
        json.dumps({"record": record, "drafts": drafts}, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="节点级 AI 审查离线基准（不落库）")
    parser.add_argument("--project")
    parser.add_argument("--node", type=int)
    parser.add_argument(
        "--out", default=str(Path(__file__).resolve().parent / "out" / datetime.now(UTC).date().isoformat())
    )
    parser.add_argument(
        "--prompt-mode",
        choices=["freeform", "checklist"],
        default=os.getenv("AICHECK_REVIEW_PROMPT_MODE", "freeform"),
        help="P8 H5：清单填表 vs 自由模式对照；结果标签带模式后缀",
    )
    args = parser.parse_args()
    os.environ["AICHECK_REVIEW_PROMPT_MODE"] = args.prompt_mode
    model_label = os.getenv("AICHECK_LLM_MODEL_REVIEW", "default") + (f"@{args.prompt_mode}" if args.prompt_mode != "freeform" else "")
    disable_persistence()
    load_state()
    samples = [(args.project, args.node)] if args.project and args.node else list(DEFAULT_SAMPLES)
    out_dir = Path(args.out)
    for project_id, node_id in samples:
        record = run_one(project_id, node_id, model_label, out_dir)
        print("RESULT", json.dumps(record, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
