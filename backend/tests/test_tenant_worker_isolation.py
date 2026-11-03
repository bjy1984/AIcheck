"""多特检院第一阶段：后台任务、定时任务、对象存储路径和任务锁都按院分开（2026-11-02）。

存储本来就按院分区（repo.state 取当前请求的院），API 请求天然隔离；这里钉住的是 API 之外
那几条原来一律落到默认院的路径。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.worker import tasks
from apps.worker.tenant_propagation import (
    TENANT_HEADER,
    enter_task_tenant,
    leave_task_tenant,
    stamp_tenant_header,
)
from libs.db.repository import repo
from libs.integrations.storage import ObjectStorage
from libs.pipeline_lock import pipeline_task_lock
from libs.security.tenant import (
    current_tenant_id,
    reset_request_tenant_id,
    set_request_tenant_id,
    tenant_scoped_name,
    valid_tenant_id,
)

OTHER = "TENANT-INSTITUTE-B"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    repo.reset()
    monkeypatch.setattr(repo, "postgres_enabled", False)
    monkeypatch.setattr(repo, "sync_postgres", None)
    monkeypatch.setattr(repo, "postgres_dsn", None)
    monkeypatch.setattr(repo, "sqlite_enabled", False)
    monkeypatch.setattr(repo, "sqlite_path", None)
    monkeypatch.setattr(repo, "configure_sync_postgres", lambda: None)
    # 别的测试会在内存里留下它们的院（repo.reset 不清），这里只从默认院开始
    monkeypatch.setattr(repo, "_tenant_states", {current_tenant_id(): repo.state})


class in_tenant:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    def __enter__(self):
        self.token = set_request_tenant_id(self.tenant_id)

    def __exit__(self, *_):
        reset_request_tenant_id(self.token)


def test_default_tenant_keeps_old_names_and_other_tenants_get_a_prefix_once():
    assert tenant_scoped_name("documents/P-1/DV-1") == "documents/P-1/DV-1"
    with in_tenant(OTHER):
        scoped = tenant_scoped_name("documents/P-1/DV-1")
        assert scoped == f"tenants/{OTHER}/documents/P-1/DV-1"
        assert tenant_scoped_name(scoped) == scoped
    assert valid_tenant_id(" TENANT-B ") == "TENANT-B"
    assert valid_tenant_id("../etc") is None and valid_tenant_id("") is None


def test_object_storage_paths_do_not_collide_across_institutes(monkeypatch):
    storage = ObjectStorage()
    monkeypatch.setattr(storage, "object_namespace", "")
    default_path = storage.object_name("documents/P-1/DV-1")
    with in_tenant(OTHER):
        other_path = storage.object_name("documents/P-1/DV-1")
        # put 返回的 minio:// 引用里存的是物理路径，读回来时不能再套一层
        assert storage.object_name(other_path) == other_path
    assert default_path == "documents/P-1/DV-1" and other_path != default_path

    monkeypatch.setattr(storage, "object_namespace", "lab")
    with in_tenant(OTHER):
        assert storage.object_name("documents/P-1/DV-1") == f"lab/tenants/{OTHER}/documents/P-1/DV-1"
        assert storage.object_name(f"lab/tenants/{OTHER}/documents/P-1/DV-1").count("tenants/") == 1


def test_task_messages_carry_the_publishers_tenant_and_workers_switch_to_it():
    headers: dict = {}
    with in_tenant(OTHER):
        stamp_tenant_header(headers=headers)
    assert headers[TENANT_HEADER] == OTHER
    # 已经写了院的不覆盖（例如显式指定了院的投递）
    stamp_tenant_header(headers=headers)
    assert headers[TENANT_HEADER] == OTHER

    task = SimpleNamespace(request=SimpleNamespace(**{TENANT_HEADER: OTHER}))
    enter_task_tenant(task=task)
    assert current_tenant_id() == OTHER
    leave_task_tenant(task=task)
    assert current_tenant_id() != OTHER

    # 消息头里的院不合法（或者老消息没有这个头）：不切换，落回默认院
    forged = SimpleNamespace(request=SimpleNamespace(**{TENANT_HEADER: "../x"}))
    enter_task_tenant(task=forged)
    assert current_tenant_id() != "../x"
    leave_task_tenant(task=forged)


def test_periodic_jobs_run_once_per_institute_against_that_institutes_data():
    repo.state["projects"] = [{"id": "P-DEFAULT"}]
    with in_tenant(OTHER):
        repo.state["projects"] = [{"id": "P-B"}]
    assert repo.persisted_tenant_ids()[0] == current_tenant_id()
    assert OTHER in repo.persisted_tenant_ids()

    seen = []

    def job():
        seen.append((current_tenant_id(), [row["id"] for row in repo.state["projects"]]))
        return {"projects": [row["id"] for row in repo.state["projects"]]}

    result = tasks._for_each_tenant(job)
    assert (OTHER, ["P-B"]) in seen and (current_tenant_id(), ["P-DEFAULT"]) in seen
    # 默认院结果原样在最外层，其他院放 otherTenants
    assert result == {"projects": ["P-DEFAULT"], "otherTenants": {OTHER: {"projects": ["P-B"]}}}


def test_single_institute_periodic_result_is_unchanged():
    assert tasks._for_each_tenant(lambda: {"completedEventIds": []}) == {"completedEventIds": []}


def test_one_institute_failing_does_not_stop_the_others():
    repo.state["projects"] = []
    with in_tenant(OTHER):
        repo.state["projects"] = []
    ran = []

    def job():
        ran.append(current_tenant_id())
        if current_tenant_id() != OTHER:
            raise RuntimeError("boom")
        return {}

    with pytest.raises(RuntimeError):
        tasks._for_each_tenant(job)
    assert OTHER in ran and len(ran) == 2


def test_pipeline_locks_are_scoped_per_institute(monkeypatch):
    keys = []

    class FakeLock:
        def __init__(self, key, **_):
            keys.append(key)

        def __enter__(self):
            return True

        def __exit__(self, *_):
            return False

    monkeypatch.setattr("libs.pipeline_lock.pipeline_lock", FakeLock)

    @pipeline_task_lock("ocr", lambda version_id: version_id)
    def parse(version_id):
        return {}

    parse("DV-1")
    with in_tenant(OTHER):
        parse("DV-1")
    assert keys == ["aicheck:ocr:DV-1", f"aicheck:ocr:tenants/{OTHER}/DV-1"]
