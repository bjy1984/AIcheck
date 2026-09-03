"""给存量的人工挂载补证据链接。

## 为什么必须有

2026-09-03 审计：人工「选择环节 + 提交」只写 node_bindings，不产 node_evidence_links，
而审查（节点 AI 复核、一键分析、自动审查）读的是链接——项目里一旦有自动打靶链接，
人工挂载的资料就被忽略（测试项目3 节点 2：已提交 3 份、AI 只看 2 份）。
提交路径已改为同步补链接，这里把改之前提交的存量补齐。

## 用法

    docker exec aicheck-api python3 /app/scripts/backfill_manual_binding_evidence_links.py [--apply] [--project P-xxx]

不加 --apply 是 dry-run，只报告不动库。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/app")

from libs.contracts.responses import server_time  # noqa: E402
from libs.manual_binding_links import (  # noqa: E402
    bindings_missing_evidence_links,
    refresh_manual_binding_links,
    upsert_manual_binding_evidence_links,
)


def main() -> int:
    from libs.db.repository import flush_state, load_state, repo

    project_id = None
    if "--project" in sys.argv:
        project_id = sys.argv[sys.argv.index("--project") + 1]
    load_state()
    missing = bindings_missing_evidence_links(repo.state, project_id)
    print(f"[{server_time()}] 已提交却没有证据链接的人工挂载 {len(missing)} 条")
    by_project: dict[str, list[dict]] = {}
    for binding in missing:
        by_project.setdefault(str(binding.get("projectId") or ""), []).append(binding)
    for pid, rows in sorted(by_project.items()):
        for row in rows:
            print(f"  {pid} 节点 {row.get('nodeId')} {row.get('fileName')} ({row.get('id')}, {row.get('bindingStatus')})")
    if "--apply" not in sys.argv:
        print("（dry-run。加 --apply 才落库）")
        return 0
    created_total = 0
    for pid, rows in sorted(by_project.items()):
        created = upsert_manual_binding_evidence_links(repo.state, pid, rows, actor_name="存量回填")
        created_total += len(created)
        for link in created:
            print(f"  已建 {link['id']} → {pid} 节点 {link['nodeId']} {link.get('fileName')}")
    refreshed = refresh_manual_binding_links(repo.state, project_id)
    for link in refreshed:
        print(f"  已重算要点 {link['id']} → {link.get('reviewPointId')} / {link.get('materialTypeCode')}")
    if created_total or refreshed:
        flush_state({"node_evidence_links"})
    print(f"共补 {created_total} 条证据链接，重算要点 {len(refreshed)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
