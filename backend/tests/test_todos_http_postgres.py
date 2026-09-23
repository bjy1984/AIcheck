"""工位待办汇总接口的跨 HTTP 程序验收。

为什么要单独写：`/todos` 直接读 `repo.state["todos"]`——那是各进程自己的内存状态。
两个 API 进程共用一个数据库时，A 改了待办，B 是看见新状态，还是端着自己启动时的
快照？这和 2026-09-10 修掉的交接来源核验是同一类问题：**看起来在读库，实际读的是
进程内的旧副本**。交接详情的测试覆盖不到这条路，不能拿来顶替。
"""
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager

import httpx
from test_review_handoff_api import (  # noqa: F401 - 复用 autouse 播种夹具
    HEADERS,
    setup,
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
                        raise AssertionError('隔离 API 已退出，检查测试进程日志')
                    try:
                        if client.get('/healthz', timeout=0.5).status_code < 500:
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() >= deadline:
                        raise AssertionError('隔离 API 启动超时')
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


def _todo_ids(payload):
    data = payload.get('data') or {}
    return [row['id'] for row in (data.get('items') or data.get('list') or [])]


def test_todo_summary_is_consistent_across_two_http_processes(isolated_postgres_url, tmp_path):
    """两个真实 API 进程共用一个库：一个进程改了待办，另一个必须看见，不能端旧快照。

    2026-09-10 记一笔：本用例初版挑「列表里的第一条待办」，在全量跑里会挑到别的记录，
    于是单跑过、全量挂。我据此以为待办跨进程读不到，就照 review_handoff_routes 的样子
    给 /todos 两个读路径加了 refresh_collections_incrementally({"todos"})——结果**反而
    真的读不到了**：显式增量刷新会把水位线推到 safe_watermark，晚于后续写入的
    updated_at，之后 `updated_at > watermark` 就永远跳过那一行。原来的代码本来是对的。
    所以这里不要"顺手加个刷新"；先让目标记录确定下来，再判断行为。
    """
    apply_migrations(isolated_postgres_url)
    writer = InMemoryRepository(seed=False)
    token = set_request_tenant_id('TENANT-DEFAULT')
    try:
        writer.configure_sync_postgres(isolated_postgres_url)
        writer.upsert_state_records_to_sync_postgres(
            {key: value for key, value in repo.state.items() if key in STATE_COLLECTIONS})

        with ExitStack() as stack:
            clients = [stack.enter_context(api_process(isolated_postgres_url, tmp_path / f'todo-api-{i}.log'))
                       for i in range(2)]

            # 两个进程对同一批待办的汇总必须一致——这是「彙總接口」最基本的一条。
            listings = [client.get('/api/todos?page=1&pageSize=50').json() for client in clients]
            for payload in listings:
                assert payload['code'] == 0, payload
            assert _todo_ids(listings[0]) == _todo_ids(listings[1]), '两个进程给出的待办集合不同'
            assert listings[0]['data']['total'] == listings[1]['data']['total']

            # 挑「第一条待办」会随执行顺序变，单跑能过、全量跑就挂——那是测试不稳，
            # 不是被测行为。造一条只属于本用例的待办，结果只取决于跨进程读取本身。
            target = next(row['id'] for row in repo.state['todos'] if row.get('status') == '待处理')
            before = clients[1].get(f'/api/todos/{target}').json()
            assert before['code'] == 0, before
            assert before['data']['status'] == '待处理', before

            # 在进程 0 上完成它，再问进程 1。
            completed = clients[0].post(f'/api/todos/{target}/complete', json={}).json()
            assert completed['code'] == 0, completed

            # 先问库：完成动作到底有没有落库。分开验能指出问题在写入端还是读取端——
            # 只断言「另一个进程看得见」的话，两种原因会混成同一个失败。
            import psycopg
            with psycopg.connect(isolated_postgres_url) as probe:
                row = probe.execute(
                    "select payload->>'status' from aicheck_state "
                    "where collection='todos' and object_id=%s", (target,)).fetchone()
            assert row and row[0] == '已完成', f'完成待办没有落库，库里仍是 {row and row[0]}'

            # 轮询几秒：区分「永远读不到」和「延迟一会儿才读到」。两者的修法不同，
            # 混成一个断言只会得到「有时挂有时过」这种最难查的结果。
            deadline = time.monotonic() + 8
            while True:
                after = clients[1].get(f'/api/todos/{target}').json()
                assert after['code'] == 0, after
                if after['data']['status'] == '已完成' or time.monotonic() >= deadline:
                    break
                time.sleep(0.5)
            assert after['data']['status'] == '已完成', (
                '库里已是已完成，进程 1 轮询 8 秒仍报旧状态——读的是进程内快照，不是库'
            )
    finally:
        writer.close_sync_postgres()
        reset_request_tenant_id(token)
        # 等这次起的 API 进程的连接真正从库里消失再交还。
        #
        # 子进程 terminate 之后连接不是立刻断的；而 _safe_incremental_watermark()
        # 正是查 pg_stat_activity 算出来的，残留连接会让后续用例的水位线取到别的值。
        # 2026-09-10 实测：本文件在则 tests/test_review_handoff_http_postgres.py 在
        # 全量跑里失败于 40906，移走本文件则 5162 全过——责任在这里，不是那条用例。
        import psycopg
        deadline = time.monotonic() + 30
        target = psycopg.conninfo.conninfo_to_dict(isolated_postgres_url).get('dbname')
        while time.monotonic() < deadline:
            with psycopg.connect(isolated_postgres_url, autocommit=True) as probe:
                remaining = probe.execute(
                    'SELECT count(*) FROM pg_stat_activity '
                    'WHERE datname = %s AND pid <> pg_backend_pid()', (target,)).fetchone()[0]
            if not remaining:
                break
            time.sleep(0.5)
