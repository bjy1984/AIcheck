"""院级审查口径开关（2026-11-04，意见反馈审批方案第二阶段）。

各院对少数「怎么判」的口径做法不同（灰区），不能写成某院专用代码，也不能逼所有院同一种。
做成开关：平台给默认值，各院可以改；多数院选同一种时，平台管理员把它升级成平台默认值。

生效顺序：本院的选择 → 平台默认（平台院 admin_config.reviewPolicyDefaults）→ 这里写的代码默认。
红线：**选项里没有「符合」**——院级口径只能更严或同等，不能放宽国家标准要求（监检有法律责任）。

审查在 worker 里跑，worker 可能很久没刷新内存里的配置；所以审查时优先从库里直接读当前院的
admin_config（缓存 30 秒），读不了才用内存。结论的工具输出里记下按哪个口径判的（policyApplied）。
"""

from __future__ import annotations

import json
import time
from typing import Any

POLICIES: dict[str, dict[str, Any]] = {
    "certificate_expired_without_construction_period": {
        "label": "证书在审查日已过期，但项目没有施工期",
        "description": "没有施工期时只能拿审查当天判有效期。当天过期不等于施工期间无效，所以默认判证据不足，"
                       "要求补施工期或证明施工期间有效。",
        "appliesTo": "证书有效期检查（设计/安装许可、焊工证、检测人员证等，check_certificate_validity）",
        "options": {
            "evidence_insufficient": "证据不足（补施工期后再判）",
            "human_review_required": "需人工确认",
            "failed": "不符合",
        },
        "default": "evidence_insufficient",
    },
    "standard_not_yet_effective_on_review_date": {
        "label": "设计引用的标准已发布，但审查日还没实施",
        "description": "设计提前采用新版标准不等于用了作废标准。默认交人工确认是否认可提前采用。",
        "appliesTo": "引用标准版本核对（check_standard_version_active）",
        "options": {
            "human_review_required": "需人工确认（是否认可提前采用）",
            "failed": "不符合（按审查日现行版本）",
        },
        "default": "human_review_required",
    },
}

CACHE_SECONDS = 30
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def options_for(key: str) -> dict[str, str]:
    return dict((POLICIES.get(key) or {}).get("options") or {})


def valid_value(key: str, value: Any) -> bool:
    return key in POLICIES and isinstance(value, str) and value in POLICIES[key]["options"]


def _clean(values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {key: value for key, value in values.items() if valid_value(key, value)}


def resolve(tenant_values: Any, platform_defaults: Any) -> dict[str, dict[str, Any]]:
    """每个开关的生效值和来源（institute / platform / code）。"""
    tenant, platform = _clean(tenant_values), _clean(platform_defaults)
    resolved: dict[str, dict[str, Any]] = {}
    for key, spec in POLICIES.items():
        if key in tenant:
            resolved[key] = {"value": tenant[key], "source": "institute"}
        elif key in platform:
            resolved[key] = {"value": platform[key], "source": "platform"}
        else:
            resolved[key] = {"value": spec["default"], "source": "code"}
    return resolved


def _admin_config_from_db(tenant_id: str) -> dict[str, Any] | None:
    from libs.db.repository import postgres_persistence_configured, repo

    if not postgres_persistence_configured():
        return None
    try:
        with repo._sync_postgres_lock:
            repo.configure_sync_postgres()
            if repo.sync_postgres is None:
                return None
            try:
                row = repo.sync_postgres.execute(
                    "SELECT payload FROM aicheck_singletons WHERE tenant_id = %s AND name = %s",
                    (tenant_id, "admin_config"),
                ).fetchone()
                # 共享连接不是自动提交：读完要结束事务，别在长时间的模型调用期间一直挂着
                repo.sync_postgres.commit()
            except Exception:
                # 出错要回滚，否则连接停在失败状态，这次审查后面的写入全会失败（2026-11-04 审计）
                repo.sync_postgres.rollback()
                raise
    except Exception:  # noqa: BLE001 -- policy lookup falls back to in-memory state; a review must not fail on it
        return None
    if not row:
        return {}
    payload = row[0]
    return payload if isinstance(payload, dict) else json.loads(payload or "{}")


def _admin_config(tenant_id: str) -> dict[str, Any]:
    from libs import institutes
    from libs.db.repository import repo

    fresh = _admin_config_from_db(tenant_id)
    if fresh is not None:
        return fresh
    # 内存兜底只用已经加载的院：没加载就用代码默认，不在审查中途整院加载
    if not repo.tenant_is_loaded(tenant_id):
        from libs.db.repository import postgres_persistence_configured

        if postgres_persistence_configured():
            return {}
    with institutes.tenant_scope(tenant_id) as state:
        config = state.get("admin_config")
        return dict(config) if isinstance(config, dict) else {}


def effective_policies(tenant_id: str | None = None) -> dict[str, dict[str, Any]]:
    """审查时用：当前院（或指定院）每个开关的生效值。缓存 30 秒。"""
    from libs.security.tenant import configured_tenant_id as platform_tenant_id
    from libs.security.tenant import current_tenant_id

    tenant = str(tenant_id or current_tenant_id())
    cached = _cache.get(tenant)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    tenant_config = _admin_config(tenant)
    platform_config = tenant_config if tenant == platform_tenant_id() else _admin_config(platform_tenant_id())
    value = resolve(tenant_config.get("reviewPolicies"), platform_config.get("reviewPolicyDefaults"))
    _cache[tenant] = (time.monotonic(), value)
    return value


def effective_value(key: str, tenant_id: str | None = None) -> str:
    try:
        return str(effective_policies(tenant_id)[key]["value"])
    except Exception:  # noqa: BLE001 -- any lookup problem means the code default, never a failed review
        return str(POLICIES[key]["default"])


def invalidate(tenant_id: str | None = None) -> None:
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop(str(tenant_id), None)
