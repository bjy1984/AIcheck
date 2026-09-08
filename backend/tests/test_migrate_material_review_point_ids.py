"""审查点 id 重键：按业务键消歧，任何阻塞项拒绝整次迁移。"""

from __future__ import annotations

from scripts.migrate_material_review_point_ids import build_id_mapping, rewrite_references

ASSET = [
    {"id": "MRP-24-welder_roster-08506E", "nodeId": 24, "materialTypeCode": "welder_roster"},
    {"id": "MRP-24-welder_certificate-NEW001", "nodeId": 24, "materialTypeCode": "welder_certificate"},
    {"id": "MRP-16-quality_certificate-A", "nodeId": 16, "materialTypeCode": "quality_certificate"},
    {"id": "MRP-16-quality_certificate-B", "nodeId": 16, "materialTypeCode": "quality_certificate"},
]


def _state() -> dict:
    return {
        "admin_config": {
            "materialReviewPoints": [
                {"id": "MRP-24-welder_roster-EE4835", "nodeId": 24, "materialTypeCode": "welder_roster"},
                {"id": "MRP-24-welder_certificate-NEW001", "nodeId": 24, "materialTypeCode": "welder_certificate"},
                {"id": "MRP-16-quality_certificate-OLD", "nodeId": 16, "materialTypeCode": "quality_certificate"},
                {"id": "MRP-99-custom-ADMIN1", "nodeId": 99, "materialTypeCode": "custom"},
            ]
        },
        "node_evidence_links": [
            {"id": "NEL-1", "reviewPointId": "MRP-24-welder_roster-EE4835"},
            {"id": "NEL-2", "reviewPointId": "MRP-16-quality_certificate-OLD"},
        ],
        "bindings": [
            {"id": "B-1", "reviewPointIds": ["MRP-24-welder_roster-EE4835", "X"], "requirementId": "MRP-24-welder_roster-EE4835"},
            {"id": "B-2", "reviewPointIds": [], "requirementId": "REQ-24-01"},
        ],
        "rectifications": [{"id": "REC-1", "supplementRequirements": [{"id": "MRP-24-welder_roster-EE4835"}]}],
    }


def test_mapping_only_covers_unique_matches() -> None:
    state = _state()
    mapping, unmatched = build_id_mapping(state["admin_config"]["materialReviewPoints"], ASSET, "engineering_inspection_v1")
    assert mapping == {"MRP-24-welder_roster-EE4835": "MRP-24-welder_roster-08506E"}
    assert [item["id"] for item in unmatched] == ["MRP-16-quality_certificate-OLD", "MRP-99-custom-ADMIN1"]
    assert unmatched[0]["candidates"] == ["MRP-16-quality_certificate-A", "MRP-16-quality_certificate-B"]


def test_rewrite_touches_every_reference_and_keeps_history() -> None:
    state = _state()
    mapping, _ = build_id_mapping(state["admin_config"]["materialReviewPoints"], ASSET, "engineering_inspection_v1")
    counts = rewrite_references(state, mapping)
    assert counts == {"materialReviewPoints": 1, "node_evidence_links": 1, "bindings": 1, "rectifications": 1}
    point = state["admin_config"]["materialReviewPoints"][0]
    assert point["id"] == "MRP-24-welder_roster-08506E" and point["previousIds"] == ["MRP-24-welder_roster-EE4835"]
    assert state["node_evidence_links"][0]["reviewPointId"] == "MRP-24-welder_roster-08506E"
    assert state["node_evidence_links"][1]["reviewPointId"] == "MRP-16-quality_certificate-OLD", "匹配不上的不动"
    assert state["bindings"][0]["reviewPointIds"] == ["MRP-24-welder_roster-08506E", "X"]
    assert state["bindings"][0]["requirementId"] == "MRP-24-welder_roster-08506E"
    assert state["bindings"][1]["requirementId"] == "REQ-24-01"
    assert state["rectifications"][0]["supplementRequirements"][0]["id"] == "MRP-24-welder_roster-08506E"


def test_mapping_cannot_take_an_existing_target_id():
    points = [
        {'id': 'MRP-OLD', 'nodeId': 1, 'materialTypeCode': 'a'},
        {'id': 'MRP-NEW', 'nodeId': 1, 'materialTypeCode': 'a'},
    ]
    mapping, unmatched = build_id_mapping(points, [{'id': 'MRP-NEW', 'nodeId': 1, 'materialTypeCode': 'a'}], 'engineering_inspection_v1')
    assert not mapping
    assert unmatched[0]['id'] == 'MRP-OLD'


def test_migration_plan_rejects_unmatched_and_orphans_without_changing_input():
    from copy import deepcopy

    from scripts.migrate_material_review_point_ids import build_migration_plan

    state = _state()
    state['bindings'].append({'id': 'orphan', 'reviewPointIds': ['MRP-MISSING']})
    original = deepcopy(state)
    report, _ = build_migration_plan(state, {'businessPackId': 'engineering_inspection_v1', 'items': ASSET}, 'engineering_inspection_v1')
    assert not report['safeToApply']
    assert report['orphanReferences'][0]['reviewPointId'] == 'MRP-MISSING'
    assert state == original


def test_safe_plan_is_idempotent_preserves_snapshots_and_requires_explicit_exclusion():
    from scripts.migrate_material_review_point_ids import build_migration_plan

    state = {
        'admin_config': {'materialReviewPoints': [
            {'id': 'MRP-OLD', 'nodeId': 1, 'materialTypeCode': 'a'},
            {'id': 'MRP-RETIRED', 'nodeId': 9, 'materialTypeCode': 'old', 'enabled': False},
        ]},
        'bindings': [{'id': 'B1', 'reviewPointIds': ['MRP-OLD']}],
        'ai_runs': [{'evidenceSnapshot': {'reviewPointId': 'MRP-OLD'}}],
    }
    asset = {'businessPackId': 'engineering_inspection_v1', 'items': [
        {'id': 'MRP-NEW', 'nodeId': 1, 'materialTypeCode': 'a'}]}
    blocked, _ = build_migration_plan(state, asset, 'engineering_inspection_v1')
    assert not blocked['safeToApply']
    report, preview = build_migration_plan(state, asset, 'engineering_inspection_v1', {'MRP-RETIRED'})
    assert report['safeToApply']
    assert report['mappingCount'] == 1
    assert preview['bindings'][0]['reviewPointIds'] == ['MRP-NEW']
    assert preview['ai_runs'] == state['ai_runs']
    rerun, _ = build_migration_plan(preview, asset, 'engineering_inspection_v1', {'MRP-RETIRED'})
    assert rerun['safeToApply'] and rerun['mappingCount'] == 0
    assert rerun['planSha256'] != report['planSha256']


def test_apply_blocked_plan_never_flushes(monkeypatch, tmp_path):
    import json

    from scripts import migrate_material_review_point_ids as migration

    asset = tmp_path / 'asset.json'
    asset.write_text(json.dumps({'businessPackId': 'engineering_inspection_v1', 'items': ASSET}))
    from contextlib import contextmanager

    @contextmanager
    def snapshot(**kwargs):
        yield _state(), None
    monkeypatch.setattr(migration, 'persistent_snapshot', snapshot)
    def forbidden(*args, **kwargs):
        raise AssertionError('blocked migration attempted persistence')
    monkeypatch.setattr(migration, 'persist_preview', forbidden)
    monkeypatch.setattr('sys.argv', ['migrate', '--asset', str(asset), '--apply', '--maintenance-confirmed', '--ids', 'MRP-OLD', '--expect-plan-sha256', 'stale'])
    assert migration.main() == 2


def test_legacy_r01_points_match_unique_document_content():
    points = [{'id': 'MRP-OLD-A', 'nodeId': 1, 'materialTypeCode': 'design_document', 'reviewContent': 'same', 'fileContent': 'seal'},
              {'id': 'MRP-OLD-B', 'nodeId': 1, 'materialTypeCode': 'design_document', 'reviewContent': 'same', 'fileContent': 'scope'}]
    asset = [{'id': 'MRP-NEW-A', 'nodeId': 1, 'materialTypeCode': 'design_document', 'reviewContent': 'identity', 'fileContent': 'seal'},
             {'id': 'MRP-NEW-B', 'nodeId': 1, 'materialTypeCode': 'design_document', 'reviewContent': 'coverage', 'fileContent': 'scope'}]
    mapping, unmatched = build_id_mapping(points, asset, 'engineering_inspection_v1')
    assert not unmatched
    assert mapping == {'MRP-OLD-A': 'MRP-NEW-A', 'MRP-OLD-B': 'MRP-NEW-B'}


def test_postgres_migration_is_read_only_until_apply_and_rolls_back(isolated_postgres_url, monkeypatch):
    import json

    import psycopg
    import pytest

    from scripts import migrate_material_review_point_ids as migration

    monkeypatch.setenv('AICHECK_DATABASE_URL', isolated_postgres_url)
    tenant = migration.current_tenant_id()
    state = {'admin_config': {'materialReviewPoints': [{'id': 'MRP-OLD', 'nodeId': 1, 'materialTypeCode': 'a'}]},
             'node_evidence_links': [{'id': 'link', 'reviewPointId': 'MRP-OLD'}],
             'bindings': [], 'rectifications': []}
    asset = {'businessPackId': 'engineering_inspection_v1', 'items': [{'id': 'MRP-NEW', 'nodeId': 1, 'materialTypeCode': 'a'}]}
    with psycopg.connect(isolated_postgres_url) as connection:
        connection.execute('CREATE TABLE aicheck_singletons (tenant_id text, name text, payload jsonb, updated_at timestamptz)')
        connection.execute('CREATE TABLE aicheck_state (tenant_id text, collection text, object_id text, payload jsonb, updated_at timestamptz)')
        connection.execute('INSERT INTO aicheck_singletons VALUES (%s, %s, %s::jsonb, now())', (tenant, 'admin_config', json.dumps(state['admin_config'])))
        connection.execute('INSERT INTO aicheck_state VALUES (%s, %s, %s, %s::jsonb, now())', (tenant, 'node_evidence_links', 'link', json.dumps(state['node_evidence_links'][0])))
    with migration.persistent_snapshot(apply=False) as (before, connection):
        assert before == state
        assert connection.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
    with pytest.raises(RuntimeError, match='simulated write failure'), migration.persistent_snapshot(apply=True) as (before, connection):
        _, preview = migration.build_migration_plan(before, asset, 'engineering_inspection_v1')
        migration.persist_preview(connection, before, preview)
        raise RuntimeError('simulated write failure')
    with migration.persistent_snapshot(apply=False) as (before, _):
        assert before == state
    with migration.persistent_snapshot(apply=True) as (before, connection):
        report, preview = migration.build_migration_plan(before, asset, 'engineering_inspection_v1')
        assert report['safeToApply']
        migration.persist_preview(connection, before, preview)
    with migration.persistent_snapshot(apply=False) as (after, _):
        assert after['node_evidence_links'][0]['reviewPointId'] == 'MRP-NEW'
        report, _ = migration.build_migration_plan(after, asset, 'engineering_inspection_v1')
        assert report['safeToApply'] and report['mappingCount'] == 0
