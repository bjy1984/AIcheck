from copy import deepcopy

import pytest

from libs.db.repository import InMemoryRepository
from libs.integrations.errors import IntegrationServiceError
from libs.review_handoff_inputs import freeze_handoff_inputs
from libs.review_live_sources import ensure_live_document_sources
from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id
from scripts.migrate_backend import apply_migrations

pytest_plugins = ["test_review_handoff_inputs"]


@pytest.mark.parametrize("change", ["verification", "source_run", "ocr", "deleted"])
def test_worker_gate_observes_other_connection_without_replacing_live_state(isolated_postgres_url, inputs, change, monkeypatch):
    state, run, selection = inputs
    run["handoffInputsSnapshot"] = freeze_handoff_inputs(run, state, selection)
    apply_migrations(isolated_postgres_url)
    writer, worker = InMemoryRepository(seed=False), InMemoryRepository(seed=False)
    token = set_request_tenant_id("T")
    try:
        writer.configure_sync_postgres(isolated_postgres_url)
        worker.configure_sync_postgres(isolated_postgres_url)
        writer.upsert_state_records_to_sync_postgres(state)
        cached = deepcopy(state)
        ensure_live_document_sources(run, cached, repository=worker)
        handoff = deepcopy(state["review_handoffs"][0])
        if change == "deleted":
            writer.sync_postgres.execute("DELETE FROM aicheck_state WHERE tenant_id = %s AND collection = 'review_handoffs' AND object_id = %s", ("T", handoff["id"]))
            writer.sync_postgres.commit()
        elif change == "verification":
            handoff["verifications"] = []
            writer.upsert_state_records_to_sync_postgres({"review_handoffs": [handoff]})
        elif change == "source_run":
            source = deepcopy(next(row for row in state["review_runs"] if row["reviewRunId"] == "SOURCE"))
            source["outputHash"] = "changed-after-model-start"
            writer.upsert_state_records_to_sync_postgres({"review_runs": [source]})
        else:
            parse = deepcopy(state["ocr_parse_results"][0])
            parse["rawText"] = "changed-after-model-start"
            writer.upsert_state_records_to_sync_postgres({"ocr_parse_results": [parse]})
        before = deepcopy(cached)
        with pytest.raises(IntegrationServiceError, match="REVIEW_INPUT_CHANGED_RECREATE_RUN"):
            ensure_live_document_sources(run, cached, repository=worker)
        from libs.db import repository as repository_module
        from libs.review_orchestrator import execution
        worker.state = cached
        monkeypatch.setattr(repository_module, "repo", worker)
        monkeypatch.setattr(execution, "repo", worker)
        previous_run = deepcopy(run)
        with pytest.raises(IntegrationServiceError, match="REVIEW_INPUT_CHANGED_RECREATE_RUN"):
            execution.run_step(run, "persist_drafts", {"findingDrafts": [{"title": "must not save stale output"}]})
        assert run == previous_run
        assert cached == before, "authoritative validation must not replace shared inflight objects"
    finally:
        reset_request_tenant_id(token)
        for repository in (writer, worker):
            if repository.sync_postgres:
                repository.sync_postgres.close()


def test_database_outage_does_not_fall_back_to_stale_memory(inputs, monkeypatch):
    from types import SimpleNamespace

    import psycopg

    state, run, selection = inputs
    run["handoffInputsSnapshot"] = freeze_handoff_inputs(run, state, selection)
    repository = SimpleNamespace(sync_postgres=SimpleNamespace(info=SimpleNamespace(dsn="unused")))
    def unavailable(*_args, **_kwargs):
        raise psycopg.OperationalError("synthetic outage")
    monkeypatch.setattr(psycopg, "connect", unavailable)
    with pytest.raises(IntegrationServiceError, match="HANDOFF_SOURCE_CHECK_UNAVAILABLE"):
        ensure_live_document_sources(run, state, repository=repository)
