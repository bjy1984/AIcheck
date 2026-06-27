from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BusinessErrorCode:
    code: int
    reason: str
    message: str


VALIDATION_ERROR = BusinessErrorCode(40001, "VALIDATION_ERROR", "请求字段校验失败。")
AUTH_REQUIRED = BusinessErrorCode(401, "AUTH_REQUIRED", "请先登录。")
FORBIDDEN = BusinessErrorCode(403, "FORBIDDEN", "当前角色无权执行该操作。")
NOT_FOUND = BusinessErrorCode(40404, "NOT_FOUND", "对象不存在或无权访问。")
CONFLICT = BusinessErrorCode(40900, "CONFLICT", "当前状态不允许执行该操作。")
TASK_RUNNING = BusinessErrorCode(40902, "TASK_RUNNING", "任务正在运行，请稍后查看进度。")
ARCHIVED_READONLY = BusinessErrorCode(40903, "ARCHIVED_READONLY", "项目已归档，只读查看。")
ETAG_CONFLICT = BusinessErrorCode(40904, "ETAG_CONFLICT", "数据版本已变化，请刷新后重试。")
FILE_TOO_LARGE = BusinessErrorCode(40016, "FILE_TOO_LARGE", "文件超过上传限制。")
UNSUPPORTED_FILE_TYPE = BusinessErrorCode(40017, "UNSUPPORTED_FILE_TYPE", "文件类型不支持。")
EMPTY_BINDINGS = BusinessErrorCode(40020, "EMPTY_BINDINGS", "资料挂载未选择有效资料。")
EMPTY_NODE_PACKAGE = BusinessErrorCode(40021, "EMPTY_NODE_PACKAGE", "当前节点没有可提交资料。")
WITHDRAW_LOCKED = BusinessErrorCode(40921, "WITHDRAW_LOCKED", "已通过或锁定资料不能撤回。")
EXPORT_TASK_NOT_READY = BusinessErrorCode(40930, "EXPORT_TASK_NOT_READY", "导出任务尚未生成完成。")
EXPORT_TASK_EXPIRED = BusinessErrorCode(41031, "EXPORT_TASK_EXPIRED", "导出任务已过期。")
EXTERNAL_TOOL_FAILED = BusinessErrorCode(50220, "EXTERNAL_TOOL_FAILED", "外部工具调用失败。")
AI_RUN_FAILED = BusinessErrorCode(50210, "AI_RUN_FAILED", "AI 审查任务失败。")


ERROR_BY_REASON = {
    item.reason: item
    for item in [
        VALIDATION_ERROR,
        AUTH_REQUIRED,
        FORBIDDEN,
        NOT_FOUND,
        CONFLICT,
        TASK_RUNNING,
        ARCHIVED_READONLY,
        ETAG_CONFLICT,
        FILE_TOO_LARGE,
        UNSUPPORTED_FILE_TYPE,
        EMPTY_BINDINGS,
        EMPTY_NODE_PACKAGE,
        WITHDRAW_LOCKED,
        EXPORT_TASK_NOT_READY,
        EXPORT_TASK_EXPIRED,
        EXTERNAL_TOOL_FAILED,
        AI_RUN_FAILED,
    ]
}
