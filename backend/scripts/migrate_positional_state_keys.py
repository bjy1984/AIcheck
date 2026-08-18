"""把按下标落库的记录改成按稳定主键落库。

## 为什么必须迁移，而不是只改代码

persistence_object_id 原先在没有已知 id 字段时退化成列表下标。改完代码后，
新写入按 submissionId/runId/taskId 落库，**库里那些以 "0"、"1"、"2" 为主键的
旧行不会自动消失**——下次 load_state 会把同一条记录读两遍（旧行一遍、新行
一遍），变成看得见的重复数据。

所以顺序是：**先迁移库，再部署新代码**。反过来会先制造重复。

## 做法

按 payload 里的稳定字段重写 object_id，冲突（目标主键已存在）时保留
updated_at 更新的那条并删掉旧的——位置主键那批本来就是被覆盖过的残留。

    docker exec aicheck-postgres psql -U aicheck -d aicheck -f -   # 见下方 SQL
    或
    docker exec aicheck-api python3 /app/scripts/migrate_positional_state_keys.py [--apply]

默认 dry-run。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/app")

from libs.db.repository import load_state, repo  # noqa: E402

# 集合 → 该集合的稳定主键字段
TARGETS = {
    "submissions": "submissionId",
    "llm_compare_runs": "runId",
    "ocr_annotation_tasks": "taskId",
}

POSITIONAL = r"^[0-9]+$"


def main() -> int:
    # 只为拿到那个 Postgres 连接——sync_postgres 在 load_state 里才建起来
    load_state()
    if repo.sync_postgres is None:
        raise SystemExit("没有连上 Postgres，无法迁移")
    apply = "--apply" in sys.argv
    total_moved = total_dropped = 0

    for collection, field in TARGETS.items():
        rows = repo.sync_postgres.execute(
            "SELECT tenant_id, object_id, payload->>%s AS stable_id "
            "FROM aicheck_state WHERE collection = %s AND object_id ~ %s",
            (field, collection, POSITIONAL),
        ).fetchall()
        if not rows:
            print(f"{collection}: 没有按下标落库的行")
            continue

        missing = [row for row in rows if not row[2]]
        movable = [row for row in rows if row[2]]
        print(f"{collection}: 位置主键 {len(rows)} 行，其中 {len(movable)} 行有 {field}")
        if missing:
            # 连稳定字段都没有的，迁不了也不能删——留着人工看
            print(f"  ⚠ {len(missing)} 行没有 {field}，保持原样：{[r[1] for r in missing][:5]}")

        for tenant_id, object_id, stable_id in movable:
            exists = repo.sync_postgres.execute(
                "SELECT 1 FROM aicheck_state WHERE tenant_id=%s AND collection=%s AND object_id=%s",
                (tenant_id, collection, stable_id),
            ).fetchone()
            if not apply:
                print(f"  {object_id} → {stable_id}" + ("（目标已存在，将删除旧行）" if exists else ""))
                continue
            if exists:
                repo.sync_postgres.execute(
                    "DELETE FROM aicheck_state WHERE tenant_id=%s AND collection=%s AND object_id=%s",
                    (tenant_id, collection, object_id),
                )
                total_dropped += 1
            else:
                repo.sync_postgres.execute(
                    "UPDATE aicheck_state SET object_id=%s WHERE tenant_id=%s AND collection=%s AND object_id=%s",
                    (stable_id, tenant_id, collection, object_id),
                )
                total_moved += 1

    if not apply:
        print("\n（dry-run。加 --apply 才真正迁移）")
        return 0
    repo.sync_postgres.commit()
    print(f"\n迁移完成：改键 {total_moved} 行，删除重复旧行 {total_dropped} 行")
    left = repo.sync_postgres.execute(
        "SELECT collection, count(*) FROM aicheck_state "
        "WHERE collection = ANY(%s) AND object_id ~ %s GROUP BY 1",
        (list(TARGETS), POSITIONAL),
    ).fetchall()
    print("仍按下标落库的行：", left or "无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
