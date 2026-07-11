from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BASELINE_COMMIT = "bdd834860a28f99b16ce61f1c56b21fb18e01a63"
GENERATED_AT = datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(name: str, payload: object) -> None:
    (ROOT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(name: str, text: str) -> None:
    (ROOT / name).write_text(text.rstrip() + "\n", encoding="utf-8")


findings = [
    {
        "id": "OCR-REAL-001",
        "severity": "P1",
        "batch": 3,
        "title": "OCR 主引擎失败后仍返回成功状态",
        "actual": "Paddle OCR 因 ResourceExhausted/MemoryError 失败，降级结果仅 1 个无 bbox 片段和 2 个低置信字段，但 API 外层仍为 code=0、status=success。",
        "expected": "关键引擎失败、必填字段/表格缺失或关键 bbox 为 0 时必须返回 partial/needs_human_review，并阻断正式证据就绪。",
        "impact": "上层可能把无原文定位、缺字段的 OCR 结果当作已完成，造成假就绪和错误审计证据。",
        "evidence": "evidence/ocr-img6514.json",
        "recommendation": "统一 OCR outcome；将 quality.status 和必填证据闸门提升为 API/任务状态，禁止 status=success 覆盖 needs_human_review。",
    },
    {
        "id": "CORE-PERF-001",
        "severity": "P1",
        "batch": 2,
        "title": "单体 JSONB 状态同步持久化导致写请求和启动超时",
        "actual": "隔离预发布完整写探针多次超过 60-120 秒并出现 ClientDisconnect；API 重启后加载大状态约 70 秒。单项对象读接口仅 0.005-0.011 秒。",
        "expected": "关键写接口在可接受 SLA 内返回排队/完成状态，API 启动和重启可快速恢复。",
        "impact": "上传、OCR 调度和正式审计链路可能形成不可恢复等待、重复点击和持续 502。",
        "evidence": "run-staging-verify.sh",
        "recommendation": "将热路径从全量 collection JSONB 刷新改为行级/增量事务写入；增加启动性能预算和慢写指标。",
    },
    {
        "id": "DEPLOY-DRIFT-001",
        "severity": "P1",
        "batch": 8,
        "title": "生产部署与冻结基线存在漂移",
        "actual": "生产 compose hash 与基线不一致；LiteLLM 实际使用 main-latest，数据库镜像也与冻结 compose 目标不同。",
        "expected": "生产静态资源、compose 和镜像 digest 与审计基线完全一致且不可变。",
        "impact": "测试结果无法证明线上运行的就是已审计版本，回滚和漏洞追踪不可复现。",
        "evidence": "evidence/production-readonly-baseline.txt",
        "recommendation": "按 baseline commit 重建并以 digest 部署，release gate 强制比较远端 compose、静态包和镜像 digest。",
    },
    {
        "id": "CRED-ROTATE-001",
        "severity": "P1",
        "batch": 8,
        "title": "模型网关凭据曾进入进程命令行可见范围",
        "actual": "活体探测期间发现敏感凭据通过命令参数传入，可被同机进程列表读取。报告未保存具体值。",
        "expected": "密钥只能通过受控 secret/env/file descriptor 注入，不得出现在 argv、日志或响应。",
        "impact": "凭据可能被同机用户或诊断工具读取。",
        "evidence": "审计会话过程证据（已脱敏）",
        "recommendation": "立即轮换相关凭据，探针改为从权限 0600 的环境文件或 secret store 读取。",
    },
    {
        "id": "STAGING-ISO-001",
        "severity": "P2",
        "batch": 7,
        "title": "对象存储 bucket 名硬编码限制预发布物理隔离",
        "actual": "预发布可隔离数据库、Redis 和 Temporal namespace，但共享 OCR 只能解析固定生产 MinIO/bucket，当前仅使用唯一对象前缀。",
        "expected": "写探针使用独立 MinIO bucket/tenant，任何故障注入不接触生产对象。",
        "impact": "无法安全执行 MinIO 故障注入，隔离强度不足。",
        "evidence": "预发布 compose 与对象探针记录",
        "recommendation": "将 bucket/tenant/endpoint 全部配置化，并允许 OCR 请求携带受控 storage namespace。",
    },
    {
        "id": "HEALTH-SEMANTICS-001",
        "severity": "P2",
        "batch": 3,
        "title": "服务健康状态未反映真实可执行能力",
        "actual": "OCR health 报告 pipeline 可用，但真实样本主引擎内存失败；PaddleOCR-VL 标记 available 时执行依赖仍不可用。Embedding /health 只返回时间戳。",
        "expected": "readiness 应执行轻量真实推理并分别报告 loaded、executable、capacity。",
        "impact": "调度层会把不可执行服务当作 ready。",
        "evidence": "evidence/ocr-img6514.json",
        "recommendation": "增加深度 readiness、最近成功时间、内存余量和模型 warmup 状态。",
    },
    {
        "id": "RELEASE-EVIDENCE-001",
        "severity": "P2",
        "batch": 8,
        "title": "容器 SBOM/Trivy 和全部故障注入证据不完整",
        "actual": "pip-audit 与 pnpm audit 为 0 漏洞，但当前环境无 Trivy；共享基础服务不能在生产只读边界下执行破坏性注入。",
        "expected": "每个发布镜像均有 SBOM 和容器扫描，所有 strict release probes 无 skip。",
        "impact": "供应链和基础设施恢复能力未达到硬门槛。",
        "evidence": "evidence/pip-audit.json, evidence/pnpm-audit.json",
        "recommendation": "在 CI/隔离预发布增加 CycloneDX、Trivy 和独立基础服务故障注入。",
    },
    {
        "id": "PNPM-OVERRIDE-001",
        "severity": "P2",
        "batch": 8,
        "title": "pnpm 安全 override 配置被当前版本忽略",
        "actual": "pnpm audit 明确警告 package.json 的 pnpm.overrides 不再读取。",
        "expected": "依赖安全 override 放在当前 pnpm 支持的配置位置并由 CI 断言生效。",
        "impact": "后续重新安装可能失去传递依赖安全约束。",
        "evidence": "evidence/pnpm-audit.json",
        "recommendation": "迁移 overrides 并对解析后的 lockfile 版本做测试。",
    },
]


batches = [
    (0, "基线冻结与预发布克隆", None, "PASS", ["基线 commit/tag 已推送", "Git LFS fsck 通过", "生产只读、预发布隔离写入"]),
    (1, "身份、权限与数据隔离", 15, "PASS", ["六角色登录与 /auth/me 通过", "dev token/mock/身份头覆盖在 strict 模式受控", "16 项定向安全测试通过"]),
    (2, "项目、资料与业务状态机", 10, "FAIL", ["36 项 readiness/状态机测试通过", "完整写探针因同步状态持久化超过 60-120 秒"]),
    (3, "OCR、证据与数据真实性", 5, "FAIL", ["真实 Scan 样本主 OCR 内存失败", "bbox 覆盖 0%，必填字段/表格/印章缺失", "外层仍返回 success"]),
    (4, "AI、RAG 与 ReviewRun", 14, "PASS_WITH_RISK", ["Qwen qwen3.7-plus 官方 API 探针通过", "本地 embedding 1024 维通过", "ReviewRun/Temporal/LangGraph/replay 通过", "知识质量 100"]),
    (5, "NDT 专项闭环", 8, "PASS_WITH_RISK", ["NDT/readiness 定向测试通过", "受第 2 批写链路性能阻断，未形成稳定完整 live 提交证据"]),
    (6, "人工结论、报告与归档", 7, "PASS_WITH_RISK", ["confirmed-only/report scope/archive 定向测试通过", "受第 2 批性能阻断，完整 live 归档探针未完成"]),
    (7, "任务、存储与故障恢复", 5, "FAIL", ["预发布 Redis 停止时登录 503，恢复后 200", "API 重启恢复约 70 秒", "共享 MinIO/OCR/embedding 不满足破坏性注入隔离"]),
    (8, "前端操作与发布门禁", 8, "FAIL", ["641 后端测试、49 Playwright、TypeScript/lint/build 通过", "28 个 route×viewport UI 审计零违规", "pip/pnpm 已知漏洞为 0", "生产部署漂移且容器扫描证据缺失"]),
]


for number, title, score, status, evidence in batches:
    related = [item for item in findings if item["batch"] == number]
    report = {
        "schemaVersion": "aicheck-core-audit-batch@1",
        "generatedAt": GENERATED_AT,
        "baselineCommit": BASELINE_COMMIT,
        "batch": number,
        "title": title,
        "status": status,
        "score": score,
        "evidence": evidence,
        "findingIds": [item["id"] for item in related],
        "productionPolicy": "read_only",
        "heavyComputePolicy": "server_only",
    }
    write_json(f"batch-{number}-report.json", report)
    write_json(f"batch-{number}-findings.json", related)
    score_line = "不计入 100 分制" if score is None else f"{score} 分"
    write_text(
        f"batch-{number}-report.md",
        f"# 第 {number} 批：{title}\n\n- 状态：**{status}**\n- 得分：**{score_line}**\n- 基线：`{BASELINE_COMMIT}`\n\n## 证据\n\n"
        + "\n".join(f"- {item}" for item in evidence)
        + "\n\n## 问题\n\n"
        + ("\n".join(f"- **{item['severity']} {item['id']}**：{item['title']}" for item in related) or "- 无新增问题。"),
    )


baseline_files = [
    "evidence/ui-visual-audit.json",
    "evidence/pnpm-audit.json",
    "evidence/pip-audit.json",
    "evidence/production-readonly-baseline.txt",
    "evidence/ocr-img6514.json",
]
write_json(
    "baseline-manifest.json",
    {
        "schemaVersion": "aicheck-audit-baseline@1",
        "generatedAt": GENERATED_AT,
        "commit": BASELINE_COMMIT,
        "tag": "audit-baseline-20260710",
        "branch": "main",
        "artifacts": [{"path": name, "sha256": sha256(ROOT / name)} for name in baseline_files],
        "regression": {
            "backendPytest": {"passed": 641, "warnings": 6},
            "playwright": {"passed": 49},
            "businessPackScore": 100,
            "knowledgeScore": 100,
            "knowledgeFiles": 60,
            "knowledgeChunks": 2134,
            "knowledgeVectors": 2134,
            "roiScore": 100,
            "frontendRoutes": 231,
            "backendRoutes": 657,
            "missingContracts": 0,
        },
    },
)

write_json(
    "business-flow-matrix.json",
    {
        "schemaVersion": "aicheck-business-flow-matrix@1",
        "stages": [
            {"stage": "资料提交", "owner": "contractor", "formalGate": "document submitted"},
            {"stage": "OCR 抽取", "owner": "system", "formalGate": "parse result + usable evidence + bbox"},
            {"stage": "证据确认", "owner": "inspection", "formalGate": "confirmed evidence only"},
            {"stage": "AI 复核", "owner": "inspection", "formalGate": "readyForAiFormal=true", "advisoryModes": ["gap_precheck", "pure_llm"]},
            {"stage": "人工结论", "owner": "inspection", "formalGate": "review opinion + confirmed evidence"},
            {"stage": "报告复核", "owner": "inspection", "formalGate": "report scoped evidence valid"},
            {"stage": "签发归档", "owner": "inspection", "formalGate": "reviewed/signed + immutable manifest"},
        ],
    },
)

write_json(
    "cross-role-permission-matrix.json",
    {
        "schemaVersion": "aicheck-role-permission-matrix@1",
        "roles": {
            "admin": ["system_admin", "project_admin", "user_admin"],
            "inspection": ["evidence_review", "ai_review", "human_opinion", "report", "archive"],
            "contractor": ["document_upload", "submit", "rectify", "resubmit"],
            "ndt": ["ndt_document", "film_record", "ndt_submit", "rectify"],
            "owner": ["project_read", "progress_read", "report_read"],
            "fde": ["business_pack_governance", "vector_quality_review", "no_formal_approval"],
        },
        "result": "targeted role and identity bypass tests passed; production digest drift prevents final release attestation",
    },
)

write_json(
    "evidence-trace-index.json",
    {
        "schemaVersion": "aicheck-evidence-trace-index@1",
        "traces": [
            {"type": "ocr", "source": "evidence/ocr-img6514.json", "result": "needs_human_review despite outer success"},
            {"type": "review_run", "reviewRunId": "RRUN-65D0666130", "result": "temporal/langgraph/replay passed"},
            {"type": "embedding", "model": "embedding-default", "dimension": 1024, "result": "passed"},
            {"type": "qwen", "model": "qwen3.7-plus", "provider": "official_api", "fallback": False, "result": "passed"},
            {"type": "knowledge", "files": 60, "chunks": 2134, "vectors": 2134, "score": 100},
        ],
    },
)

write_json(
    "fault-injection-report.json",
    {
        "schemaVersion": "aicheck-fault-injection@1",
        "environment": "isolated_staging",
        "tests": [
            {"component": "redis", "before": 200, "during": 503, "after": 200, "result": "pass_fail_closed"},
            {"component": "api", "recoverySeconds": 70, "result": "fail_sla"},
            {"component": "write_pipeline", "timeoutSeconds": [60, 120], "result": "fail_timeout"},
            {"component": "postgres/minio/ocr/embedding", "result": "not_run", "reason": "not physically isolated from production"},
        ],
    },
)

score = sum(item[2] or 0 for item in batches)
severity_counts = {level: sum(1 for item in findings if item["severity"] == level) for level in ("P0", "P1", "P2", "P3")}
final = {
    "schemaVersion": "aicheck-final-core-audit@1",
    "generatedAt": GENERATED_AT,
    "baselineCommit": BASELINE_COMMIT,
    "score": score,
    "decision": "NO-GO",
    "severityCounts": severity_counts,
    "hardGateFailures": [
        "P1 findings are not zero",
        "OCR key field/bbox accuracy gate is not met",
        "critical write probe does not complete within SLA",
        "production digest differs from audited baseline",
        "strict release probes include skips",
    ],
    "batchScores": [{"batch": n, "title": t, "score": s, "status": st} for n, t, s, st, _ in batches if s is not None],
    "findings": findings,
    "positiveEvidence": [
        "641 backend tests passed",
        "49 Playwright tests passed",
        "six-role targeted authorization tests passed",
        "knowledge and ROI audits scored 100",
        "Qwen official API, local embedding and ReviewRun probes passed",
        "Redis strict fail-closed and recovery passed",
        "pip-audit and pnpm audit reported zero known vulnerabilities",
        "28 route/viewport visual checks reported zero violations",
    ],
}
write_json("findings.json", findings)
write_json("final-core-audit-report.json", final)

write_text(
    "final-core-audit-report.md",
    f"""# AIcheck 核心功能深度审计报告

## 结论

- 决策：**NO-GO**
- 真实综合分：**{score}/100**
- 基线：`{BASELINE_COMMIT}` (`audit-baseline-20260710`)
- 问题：P0 {severity_counts['P0']}、P1 {severity_counts['P1']}、P2 {severity_counts['P2']}、P3 {severity_counts['P3']}

分数不能覆盖硬门槛。当前存在 OCR 假成功、关键写链路超时、生产部署漂移和凭据轮换四项 P1，因此不能稳定上线。

## 批次得分

| 批次 | 范围 | 得分 | 状态 |
|---:|---|---:|---|
"""
    + "\n".join(f"| {n} | {t} | {s} | {st} |" for n, t, s, st, _ in batches if s is not None)
    + "\n\n## P1 阻断项\n\n"
    + "\n".join(f"- **{item['id']}**：{item['title']}。{item['impact']}" for item in findings if item["severity"] == "P1")
    + "\n\n## 已验证能力\n\n"
    + "\n".join(f"- {item}" for item in final["positiveEvidence"]),
)

write_text(
    "release-go-no-go.md",
    f"""# Release GO / NO-GO

**结论：NO-GO（{score}/100）**

以下硬门槛未通过：

1. P1 问题不为 0。
2. OCR 真实样本关键字段和 bbox 未达到 98%。
3. 上传/OCR 写链路在 60-120 秒内不稳定收敛。
4. 生产 compose/镜像与冻结审计基线不一致。
5. 容器扫描和全部隔离故障探针存在 skip。

解除 NO-GO 的最短路径：先修复 OCR outcome 闸门和状态持久化性能，再部署基线 digest、轮换凭据、补齐独立对象存储及容器扫描，最后复跑第 2、3、7、8 批和完整 release gate。
""",
)

print(json.dumps({"score": score, "decision": "NO-GO", "findings": severity_counts}, ensure_ascii=False))
