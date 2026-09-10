"""增量刷新的水位线边界：写入时刻正好等于水位线的那次修改，不能被跳过。

updated_at 取 now()，在 PostgreSQL 里是**事务开始时刻**；水位线取最老活跃事务的
xact_start。两者可以正好相等——严格大于会把那次修改永久跳过，内存里的 state 与
_persistence_baseline 一起停在旧值，该进程之后再写同一条记录就必然报
RESOURCE_STATE_CHANGED，重读也救不回来。

2026-09-10 的受控实验：把查询改回 `>`，
tests/test_review_handoff_http_postgres.py 与任意第二个测试文件同跑就稳定失败在
40906；改成 `>=` 即通过，来回切换都复现。

这里验的是**已有记录被改**的情形，不是新增记录——新增的那条即使不在 changed 里，
也会经 live_ids 补进内存，所以用新增来验会得到一条永远通过的测试（初版就是这样）。
"""
import psycopg

from libs.db.repository import InMemoryRepository
from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id
from scripts.migrate_backend import apply_migrations

TENANT = 'TENANT-DEFAULT'


def test_an_update_written_at_exactly_the_watermark_is_not_skipped(isolated_postgres_url):
    apply_migrations(isolated_postgres_url)
    token = set_request_tenant_id(TENANT)
    repo = InMemoryRepository(seed=False)
    try:
        repo.configure_sync_postgres(isolated_postgres_url)
        with psycopg.connect(isolated_postgres_url, autocommit=True) as writer:
            writer.execute(
                "INSERT INTO aicheck_state (tenant_id, collection, object_id, payload) "
                "VALUES (%s,%s,%s,%s::jsonb)",
                (TENANT, 'todos', 'TODO-WM', '{"id": "TODO-WM", "status": "待处理"}'))
            repo.load_collections_into_state(['todos'], tenant_id=TENANT)
            assert repo.find_one('todos', 'TODO-WM')['status'] == '待处理'

            # 改这条已有记录，并把 updated_at 钉在一个确定时刻；水位线设成同一时刻。
            moment = writer.execute('SELECT now()').fetchone()[0]
            writer.execute(
                "UPDATE aicheck_state SET payload=%s::jsonb, updated_at=%s "
                "WHERE tenant_id=%s AND collection=%s AND object_id=%s",
                ('{"id": "TODO-WM", "status": "已完成"}', moment, TENANT, 'todos', 'TODO-WM'))
        repo._collection_watermarks[(TENANT, 'todos')] = moment

        repo.refresh_collections_incrementally({'todos'}, tenant_id=TENANT, strict=True)

        assert repo.find_one('todos', 'TODO-WM')['status'] == '已完成', (
            '写入时刻正好等于水位线的那次修改被跳过了——增量查询必须用 >= 而不是 >'
        )
        # 基准必须一起更新，否则该进程之后写这条记录会被乐观锁拒绝且无法自愈。
        # canonical_persistence_payload 返回的是规范化后的字符串，不是 dict。
        baseline = repo._persistence_baseline.get(('todos', 'TODO-WM'))
        assert baseline and '已完成' in str(baseline), baseline
    finally:
        repo.close_sync_postgres()
        reset_request_tenant_id(token)
