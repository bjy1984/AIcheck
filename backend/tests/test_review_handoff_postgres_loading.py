from copy import deepcopy

from libs.db.repository import InMemoryRepository
from libs.review_handoff_inputs import freeze_handoff_inputs, handoff_dependency_status
from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id
from scripts.migrate_backend import apply_migrations

pytest_plugins = ["test_review_handoff_inputs"]


def test_worker_loads_dependency_graph_and_drops_deleted_cached_handoff(isolated_postgres_url, inputs):
    state, run, selection = inputs
    run["handoffInputsSnapshot"] = freeze_handoff_inputs(run, state, selection)
    unrelated = deepcopy(state["review_runs"][0])
    unrelated.update(id="UNRELATED", reviewRunId="UNRELATED")
    state["review_runs"].append(unrelated)
    apply_migrations(isolated_postgres_url)
    writer, worker = InMemoryRepository(seed=False), InMemoryRepository(seed=False)
    token = set_request_tenant_id("T")
    try:
        writer.configure_sync_postgres(isolated_postgres_url)
        worker.configure_sync_postgres(isolated_postgres_url)
        writer.upsert_state_records_to_sync_postgres(state)
        worker.load_review_run_scope_from_sync_postgres("NEXT")
        loaded = worker.find_one("review_runs", "NEXT", id_field="reviewRunId")
        assert {row["reviewRunId"] for row in worker.state["review_runs"]} == {"SOURCE", "TARGET", "NEXT"}
        assert len(worker.state["ocr_parse_results"]) == 1
        assert handoff_dependency_status(loaded, worker.state)["status"] == "current"
        handoff_id = state["review_handoffs"][0]["id"]
        writer.sync_postgres.execute("DELETE FROM aicheck_state WHERE tenant_id = %s AND collection = 'review_handoffs' AND object_id = %s", ("T", handoff_id))
        writer.sync_postgres.commit()
        worker.load_review_run_scope_from_sync_postgres("NEXT")
        loaded = worker.find_one("review_runs", "NEXT", id_field="reviewRunId")
        assert worker.state["review_handoffs"] == []
        assert handoff_dependency_status(loaded, worker.state)["requiresRevalidation"] is True
    finally:
        reset_request_tenant_id(token)
        for repository in (writer, worker):
            if repository.sync_postgres:
                repository.sync_postgres.close()
