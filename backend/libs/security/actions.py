from __future__ import annotations

import re


MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

ACTION_ROUTE_RULES: tuple[tuple[str, str, str], ...] = (
    ("POST", r"/business-packs/[^/]+/validate$", "knowledge:view"),
    ("POST", r"/business-packs/validate-all$", "knowledge:view"),
    ("POST", r"/projects$", "admin:config"),
    ("PATCH", r"/projects/[^/]+$", "admin:config"),
    ("POST", r"/projects/[^/]+/business-pack/apply$", "admin:config"),
    ("POST", r"/projects/[^/]+/participants$", "admin:config"),
    ("PATCH", r"/projects/[^/]+/participants/[^/]+$", "admin:config"),
    ("POST", r"/projects/[^/]+/members$", "project:authorize-member"),
    ("PUT", r"/projects/[^/]+/members/[^/]+$", "project:authorize-member"),
    ("POST", r"/projects/[^/]+/initialize-workflow$", "admin:config"),
    ("POST", r"/projects/[^/]+/documents/upload-session$", "file:upload"),
    ("POST", r"/projects/[^/]+/documents/upload-session/[^/]+/complete$", "file:upload"),
    ("POST", r"/projects/[^/]+/documents/[^/]+/versions$", "file:upload"),
    ("POST", r"/projects/[^/]+/documents/bindings$", "file:bind"),
    ("PATCH", r"/projects/[^/]+/documents/bindings/[^/]+$", "file:bind"),
    ("DELETE", r"/projects/[^/]+/documents/bindings/[^/]+$", "file:bind"),
    ("POST", r"/projects/[^/]+/documents/[^/]+/withdraw$", "file:withdraw"),
    ("POST", r"/projects/[^/]+/documents/[^/]+/void$", "file:withdraw"),
    ("POST", r"/projects/[^/]+/documents/batch-classify$", "file:bind"),
    ("POST", r"/projects/[^/]+/submissions/drafts$", "submission:draft"),
    ("POST", r"/projects/[^/]+/submissions$", "submission:submit"),
    ("POST", r"/projects/[^/]+/submissions/[^/]+/withdraw-items$", "submission:withdraw"),
    ("POST", r"/projects/[^/]+/rectifications$", "rectification:submit"),
    ("POST", r"/projects/[^/]+/inspection/nodes/[^/]+/attachments$", "file:upload"),
    ("POST", r"/projects/[^/]+/inspection/nodes/[^/]+/file-bindings$", "file:bind"),
    ("POST", r"/projects/[^/]+/inspection/nodes/[^/]+/ai-recheck$", "ai:recheck"),
    ("POST", r"/projects/[^/]+/inspection/nodes/[^/]+/review-opinions$", "review:save"),
    ("POST", r"/projects/[^/]+/inspection/nodes/[^/]+/ai-suggestions/[^/]+/adopt$", "ai:adopt"),
    ("POST", r"/projects/[^/]+/inspection/nodes/[^/]+/ai-suggestions/[^/]+/reject$", "ai:reject"),
    ("POST", r"/projects/[^/]+/inspection/nodes/[^/]+/actions/return-correction$", "review:return-correction"),
    ("POST", r"/projects/[^/]+/inspection/nodes/[^/]+/report-review$", "report:generate"),
    ("PATCH", r"/projects/[^/]+/reports/[^/]+$", "report:review"),
    ("POST", r"/projects/[^/]+/reports/[^/]+/export$", "report:export"),
    ("POST", r"/projects/[^/]+/reports/[^/]+/archive$", "report:archive"),
    ("POST", r"/exports$", "admin:export"),
    ("POST", r"/projects/[^/]+/ndt/films$", "ndt:film-create"),
    ("PATCH", r"/projects/[^/]+/ndt/films/[^/]+$", "ndt:film-create"),
    ("POST", r"/projects/[^/]+/ndt/films/import$", "ndt:film-create"),
    ("POST", r"/projects/[^/]+/ndt/records/import$", "ndt:record-import"),
    ("POST", r"/projects/[^/]+/ndt/reports/upload-session$", "ndt:report-upload"),
    ("POST", r"/projects/[^/]+/ndt/submissions$", "ndt:submit"),
    ("POST", r"/projects/[^/]+/ndt/rectifications$", "rectification:submit"),
    ("POST", r"/todos/[^/]+/(complete|defer)$", "todo:update"),
    ("POST", r"/messages/[^/]+/read$", "message:update"),
    ("POST", r"/messages/read-all$", "message:update"),
    ("POST", r"/workflow/commands$", "admin:config"),
    ("POST", r"/review/findings$", "review:save"),
    ("POST", r"/review/findings/[^/]+/(accept|reject)$", "review:save"),
    ("POST", r"/review-runs/[^/]+/human-decision$", "review:save"),
    ("POST", r"/review-runs/[^/]+/rerun$", "ai:recheck"),
    ("POST", r"/review-runs/[^/]+/cancel$", "ai:recheck"),
    ("POST", r"/ai/runs/[^/]+/feedback$", "ai:adopt"),
    ("POST", r"/fde/ai-runs/[^/]+/replay$", "fde:ai-run:replay"),
    ("POST", r"/fde/review-runs/[^/]+/(replay|shadow-run)$", "fde:ai-run:replay"),
    ("POST", r"/fde/access-grants/request$", "fde:security:manage"),
    ("POST", r"/fde/access-grants/[^/]+/approve$", "admin:config"),
    ("POST", r"/fde/data-exports$", "fde:security:manage"),
    ("POST", r"/fde/feedback/[^/]+/triage$", "fde:feedback:triage"),
    ("POST", r"/fde/evaluation-runs$", "fde:evaluation:run"),
    ("POST", r"/fde/ocr-corrections$", "fde:ocr-quality:view"),
    ("POST", r"/fde/ocr-evaluation-runs$", "fde:evaluation:run"),
    ("POST", r"/fde/capability-bundles$", "fde:capability-bundle:manage"),
    ("POST", r"/fde/releases$", "fde:release:submit"),
    ("POST", r"/fde/releases/[^/]+/submit$", "fde:release:submit"),
    ("POST", r"/fde/releases/[^/]+/start-shadow$", "fde:release:shadow"),
    ("POST", r"/fde/releases/[^/]+/request-canary$", "fde:release:canary"),
    ("POST", r"/fde/releases/[^/]+/rollback$", "fde:release:rollback"),
    ("POST", r"/fde/business-packs/validate-all$", "fde:business-pack:validate"),
    ("POST", r"/fde/business-packs/[^/]+/(install|upgrade|rollback)$", "fde:business-pack:install"),
    ("POST", r"/fde/incidents/[^/]+/rca$", "fde:incident:manage"),
    ("POST", r"/knowledge/sources$", "knowledge:manage"),
    ("PATCH", r"/knowledge/sources/[^/]+$", "knowledge:manage"),
    ("PUT", r"/knowledge/sources/[^/]+$", "knowledge:manage"),
    ("POST", r"/knowledge/sources/[^/]+/(enable|disable)$", "knowledge:manage"),
    ("POST", r"/knowledge/files/[^/]+/reindex$", "knowledge:manage"),
    ("POST", r"/knowledge/tasks/[^/]+/(retry|cancel)$", "knowledge:manage"),
    ("POST", r"/knowledge/reindex$", "knowledge:manage"),
    ("POST", r"/knowledge/retrieval-test$", "knowledge:view"),
    ("PATCH", r"/knowledge/config$", "knowledge:manage"),
    ("PUT", r"/knowledge/config$", "knowledge:manage"),
    ("POST", r"/rules/versions/[^/]+/(publish|rollback)$", "knowledge:manage"),
    ("POST", r"/llm/compare$", "llm:compare"),
    ("POST", r"/admin/config-export$", "admin:export"),
    ("POST", r"/admin/.*", "admin:config"),
    ("PATCH", r"/admin/.*", "admin:config"),
    ("PUT", r"/admin/.*", "admin:config"),
)


def canonical_path(path: str) -> str:
    normalized = path or "/"
    if normalized.startswith("/api/"):
        normalized = normalized[4:]
    elif normalized == "/api":
        normalized = "/"
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized


def required_action_for_request(method: str, path: str) -> str | None:
    normalized_method = method.upper()
    if normalized_method not in MUTATING_METHODS:
        return None
    normalized_path = canonical_path(path)
    for rule_method, pattern, action in ACTION_ROUTE_RULES:
        if rule_method == normalized_method and re.fullmatch(pattern, normalized_path):
            return action
    return None
