import json
import subprocess
import sys
from copy import deepcopy

import pytest

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


@pytest.mark.parametrize("change", ["source", "delete_handoff"])
def test_api_repository_refresh_observes_separate_process_change(isolated_postgres_url, inputs, change):
    state, run, selection = inputs
    run["handoffInputsSnapshot"] = freeze_handoff_inputs(run, state, selection)
    apply_migrations(isolated_postgres_url)
    reader = InMemoryRepository(seed=False)
    token = set_request_tenant_id("T")
    try:
        reader.configure_sync_postgres(isolated_postgres_url)
        reader.upsert_state_records_to_sync_postgres(state)
        reader.load_collections_into_state(list(state))
        reader.refresh_stale_state_from_postgres(tenant_id="T", force=True)
        before = deepcopy(reader.find_one("review_runs", "NEXT", id_field="reviewRunId"))
        assert handoff_dependency_status(before, reader.state)["status"] == "current"
        script = """
import json, sys
import psycopg
settings = json.load(sys.stdin)
with psycopg.connect(settings['dsn']) as connection:
    if settings['change'] == 'source':
        connection.execute("UPDATE aicheck_state SET payload = jsonb_set(payload, '{inputHash}', %s::jsonb), updated_at = clock_timestamp() WHERE tenant_id = %s AND collection = 'review_runs' AND object_id = %s", (json.dumps("changed-by-second-process"), 'T', 'SOURCE'))
    else:
        connection.execute("DELETE FROM aicheck_state WHERE tenant_id = %s AND collection = 'review_handoffs' AND object_id = %s", ('T', settings['handoff']))
"""
        subprocess.run([sys.executable, "-c", script], input=json.dumps({
            "dsn": isolated_postgres_url, "change": change, "handoff": state["review_handoffs"][0]["id"],
        }), text=True, check=True, capture_output=True, timeout=30)
        # Explicit handoff status reads refresh dependency collections, including removed rows.
        reader.refresh_collections_incrementally(set(state), tenant_id="T")
        current = reader.find_one("review_runs", "NEXT", id_field="reviewRunId")
        assert current == before
        assert handoff_dependency_status(current, reader.state)["requiresRevalidation"] is True
    finally:
        reset_request_tenant_id(token)
        if reader.sync_postgres:
            reader.sync_postgres.close()
