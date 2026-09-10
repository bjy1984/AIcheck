"""Two real loopback API processes share an isolated PostgreSQL database."""
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from threading import Barrier

import httpx
from test_review_handoff_api import (  # noqa: F401 - shared autouse seed fixture
    HEADERS,
    setup,
    verification_fixture,
)

from libs.db.repository import STATE_COLLECTIONS, InMemoryRepository, repo
from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id
from scripts.migrate_backend import apply_migrations

SERVER = """
import json, os, sys
settings = json.loads(sys.stdin.readline())
os.environ.update(AICHECK_REQUIRE_AUTH='false', AICHECK_ALLOW_DEV_TOKENS='true',
    AICHECK_REQUIRE_IF_MATCH='false', AICHECK_SQLITE_DISABLE='true',
    AICHECK_ENABLE_DEMO_DATA='true', AICHECK_ENABLE_COMPATIBILITY_MOCKS='true',
    AICHECK_WORKSTATIONS_ENABLED='true', AICHECK_DATABASE_URL='', DATABASE_URL='')
from apps.api.main import app
from libs.db.repository import repo, STATE_COLLECTIONS
repo.configure_sync_postgres(settings['dsn'])
repo.load_collections_into_state(list(STATE_COLLECTIONS))
import uvicorn
uvicorn.run(app, fd=settings['fd'], lifespan='off', log_level='error', access_log=False)
"""


@contextmanager
def api_process(dsn, log_path):
    # Reserve a loopback socket; avoid port races and external binding.
    with socket.socket() as listener, log_path.open('w+') as log:
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        env = dict(os.environ)
        env.pop('AICHECK_STRICT_PRODUCTION', None)
        process = subprocess.Popen([sys.executable, '-c', SERVER], stdin=subprocess.PIPE,
                                   stdout=log, stderr=log, text=True, env=env,
                                   pass_fds=(listener.fileno(),))
        try:
            process.stdin.write(json.dumps({'dsn': dsn, 'fd': listener.fileno()}) + '\n')
            process.stdin.flush()
            process.stdin.close()
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', headers=HEADERS,
                              trust_env=False, timeout=15) as client:
                deadline = time.monotonic() + 60
                while True:
                    if process.poll() is not None:
                        raise AssertionError('isolated API exited; inspect test process log')
                    try:
                        response = client.get('/healthz', timeout=0.5)
                        if response.status_code < 500:
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() >= deadline:
                        raise AssertionError('isolated API startup timed out')
                    time.sleep(0.1)
                yield client
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def test_two_http_processes_reject_stale_verification_and_refresh_source(isolated_postgres_url, tmp_path):
    url, original, body = verification_fixture()
    before_runs = deepcopy(repo.state['review_runs'])
    apply_migrations(isolated_postgres_url)
    writer = InMemoryRepository(seed=False)
    token = set_request_tenant_id('TENANT-DEFAULT')
    try:
        writer.configure_sync_postgres(isolated_postgres_url)
        writer.upsert_state_records_to_sync_postgres({key: value for key, value in repo.state.items()
                                                     if key in STATE_COLLECTIONS})
        with ExitStack() as stack:
            clients = [stack.enter_context(api_process(isolated_postgres_url, tmp_path / f'api-{i}.log'))
                       for i in range(2)]
            endpoint = f"{url}/{original['id']}"
            for client in clients:
                response = client.get(endpoint).json()
                assert response['code'] == 0, response
                assert response['data'].get('verifications', []) == []
            barrier = Barrier(2)

            def verify(index):
                barrier.wait(timeout=10)
                return clients[index].post(endpoint + '/verifications', json={
                    **body, 'note': f'synthetic reviewer {index}',
                }, headers={'Idempotency-Key': f'parallel-{index}'}).json()

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(verify, range(2)))
            assert sum(item['code'] == 0 for item in responses) == 1, responses
            rejected = next(item for item in responses if item['code'] != 0)
            assert rejected['code'] in {40906, 40001}, rejected
            if rejected['code'] == 40001:
                assert rejected['message'] == 'handoff_verification_revision_changed'
            saved = next(item['data'] for item in responses if item['code'] == 0)
            assert len(saved['verifications']) == 1
            for client in clients:
                listing = client.get(url).json()['data']['items']
                assert next(row for row in listing if row['id'] == original['id'])['verifications'] == saved['verifications']
                current = client.get(endpoint).json()['data']
                assert current['verifications'] == saved['verifications']
                assert current['verification']['status'] == 'verified'
            revised = clients[1].post(endpoint + '/verifications', json={
                **body, 'expectedPreviousId': saved['verifications'][0]['id'],
                'outcome': 'rejected', 'objectMatchConfirmed': False,
                'note': 'synthetic correction after reread',
            }).json()
            assert revised['code'] == 0, revised
            assert len(revised['data']['verifications']) == 2
            assert clients[0].get(endpoint).json()['data']['verification']['status'] == 'rejected'
            writer.sync_postgres.execute(
                "UPDATE aicheck_state SET payload = jsonb_set(payload, '{inputHash}', %s::jsonb), "
                "updated_at = clock_timestamp() WHERE tenant_id = %s AND collection = 'review_runs' AND object_id = %s",
                (json.dumps('source-changed-after-verification'), 'TENANT-DEFAULT', 'SOURCE'))
            writer.sync_postgres.commit()
            for client in clients:
                stale = client.get(endpoint).json()['data']
                assert stale['verification']['status'] == 'stale'
                assert stale['verifications'] == revised['data']['verifications']
        with api_process(isolated_postgres_url, tmp_path / 'api-restarted.log') as restarted:
            restored = restarted.get(endpoint).json()['data']
            assert restored['verification']['status'] == 'stale'
            assert restored['verifications'] == revised['data']['verifications']
        writer.load_collections_into_state(['review_runs', 'review_handoffs', 'ai_runs'])
        assert len(writer.state['review_handoffs'][0]['verifications']) == 2
        expected = deepcopy(before_runs)
        next(run for run in expected if run['id'] == 'SOURCE')['inputHash'] = 'source-changed-after-verification'
        assert sorted(writer.state['review_runs'], key=lambda row: row['id']) == sorted(expected, key=lambda row: row['id'])
        assert writer.state['ai_runs'] == repo.state['ai_runs']
    finally:
        writer.close_sync_postgres()
        reset_request_tenant_id(token)
