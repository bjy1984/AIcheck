"""写操作实操审计：六个角色的主线写操作在线上真跑一遍。

## 与 online_probe 的分工

online_probe 是「读断言」：接口回答得对不对。这里是「写实操」：每个角色
用自己的身份把主线写操作真的做一遍，验证三件事——

1. **该成的成**：写进去了，再读出来是那个值（不是只看 code=0）；
2. **该拦的拦**：越权写被 403，只读角色（owner）与平台角色（fde）碰不了业务写；
3. **不留垃圾**：所有业务写都发生在本脚本创建的专用审计项目里，收尾整个删掉。

## 安全边界

- 在 API 容器内用 issue_token() 自签令牌，不碰口令，令牌不出容器；
- 全部写操作限定在名字带「写操作审计」的临时项目；
- 收尾 DELETE 该项目；FDE 的全局写（向量修正）当场自我驳回，留痕注明是审计探针。

## 用法

    docker exec aicheck-api python3 /app/scripts/write_ops_audit.py [--keep]

--keep 保留审计项目不删（复查现场用）。每步打印「判据 -> 实测」，
任何一步失败继续跑完，最后汇总并以非零退出码结束。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime

sys.path.insert(0, "/app")

BASE = "http://127.0.0.1:8000"

USERS = {
    "admin": ("admin", "USER-ADMIN-001"),
    "inspection": ("inspection", "USER-INSPECTION-001"),
    "contractor": ("contractor", "USER-CONTRACTOR-001"),
    "ndt": ("ndt", "USER-NDT-001"),
    "owner": ("owner", "USER-OWNER-001"),
    "fde": ("fde", "USER-FDE-001"),
}

_tokens: dict[str, str] = {}
_state_loaded = False

RESULTS: list[tuple[str, bool, str]] = []


def record(step: str, ok_: bool, detail: str = "") -> bool:
    RESULTS.append((step, ok_, detail))
    print(f"{'✓' if ok_ else '✗'} {step}" + (f"：{detail}" if detail else ""))
    return ok_


def token_for(role: str) -> str:
    global _state_loaded
    if role not in _tokens:
        from libs.security.auth import issue_token, user_record_by_username

        if not _state_loaded:
            from libs.db.repository import load_state

            load_state()
            _state_loaded = True
        user = user_record_by_username(USERS[role][0])
        if not user:
            raise SystemExit(f"找不到用户 {USERS[role][0]}")
        _tokens[role] = issue_token(user)
    return _tokens[role]


def api(
    path: str,
    role: str,
    payload: dict | None = None,
    method: str | None = None,
    raw_body: bytes | None = None,
    extra_headers: dict | None = None,
) -> dict:
    headers = {
        "Authorization": f"Bearer {token_for(role)}",
        "Content-Type": "application/json",
        "X-Role": role,
        "X-User-Id": USERS[role][1],
        "If-Match": "*",
        **(extra_headers or {}),
    }
    data = raw_body if raw_body is not None else (json.dumps(payload).encode() if payload is not None else None)
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers=headers,
        method=method or ("POST" if data is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read().decode())
        except Exception:
            return {"code": error.code, "message": f"HTTP {error.code}"}


def expect_ok(step: str, body: dict, detail_key: str | None = None) -> dict | None:
    if body.get("code") == 0:
        detail = ""
        if detail_key:
            detail = str((body.get("data") or {}).get(detail_key, ""))
        record(step, True, detail)
        return body.get("data") or {}
    record(step, False, f"code={body.get('code')} msg={body.get('message') or body.get('detail')}")
    return None


def expect_denied(step: str, body: dict) -> bool:
    denied = body.get("code") not in (0, None) or body.get("detail") is not None
    msg = str(body.get("message") or body.get("detail") or "")
    return record(step, denied, f"code={body.get('code')} msg={msg[:60]}" if denied else "竟然成功了——越权写没有被拦住")


def main() -> int:
    keep = "--keep" in sys.argv
    stamp = datetime.now(UTC).strftime("%m%d%H%M")

    # ---------------- admin：项目全生命周期 ----------------
    print("\n== admin：建项目 / 改项目 / 参建单位 / 成员授权 / 负责人 / 注册链接 ==")
    body = api(
        "/api/projects",
        "admin",
        {
            "name": f"写操作审计-勿动-{stamp}",
            "region": "审计专用",
            "ownerOrgName": "华东管网建设公司",
            "contractorOrgName": "中石化安装有限公司",
            "ndtOrgName": "华测检测有限公司",
            "inspectionOrgName": "省特检院一部",
            "memberUserIds": {
                "owner": "USER-OWNER-001",
                "contractor": "USER-CONTRACTOR-001",
                "ndt": "USER-NDT-001",
                "inspection": "USER-INSPECTION-001",
            },
        },
    )
    data = expect_ok("admin 创建审计项目", body)
    if not data:
        print("项目都建不起来，后面无从审计")
        return finish(None, keep)
    project = data.get("project") or {}
    pid = project.get("id") or (body.get("data") or {}).get("projectId")
    if not pid:
        record("拿到项目 ID", False, json.dumps(data)[:200])
        return finish(None, keep)
    record("拿到项目 ID", True, pid)

    detail = api(f"/api/projects/{pid}", "admin")
    expect_ok("admin 读回项目详情", detail)

    upd = api(f"/api/projects/{pid}", "admin", {"region": "审计专用-已改"}, method="PUT")
    after = api(f"/api/projects/{pid}", "admin")
    persisted = ((after.get("data") or {}).get("project") or {}).get("region") == "审计专用-已改"
    record("admin 改项目字段并读回", upd.get("code") == 0 and persisted, f"region={((after.get('data') or {}).get('project') or {}).get('region')}")

    part = api(
        f"/api/projects/{pid}/participants",
        "admin",
        {"unitType": "contractor", "unitName": "中石化安装有限公司", "contactName": "审计探针", "contactPhone": "13800000000"},
    )
    expect_ok("admin 保存参建单位联系人", part)

    members = ((api(f"/api/projects/{pid}", "admin").get("data") or {}).get("members")) or []
    con_member = next((m for m in members if m.get("role") == "contractor"), None)
    if con_member:
        lead = api(
            f"/api/projects/{pid}/members/{con_member['id']}",
            "admin",
            {"isProjectLeader": True},
            method="PUT",
        )
        members2 = ((api(f"/api/projects/{pid}", "admin").get("data") or {}).get("members")) or []
        now_leader = any(m.get("id") == con_member["id"] and m.get("isProjectLeader") for m in members2)
        record("admin 设项目负责人并读回", lead.get("code") == 0 and now_leader)
    else:
        record("找到 contractor 成员", False, f"members={len(members)}")

    link = api(f"/api/projects/{pid}/registration-links", "admin", {})
    link_data = expect_ok("admin 生成注册链接", link, "token")
    reg_token = (link_data or {}).get("token")

    # ---------------- contractor：上传 → 绑定 → 报审 ----------------
    print("\n== contractor：上传资料 / 挂载节点 / 报审 ==")
    node_id = 16
    # 素材必须像真实资料，否则测的不是产品而是探针自己。
    #
    # 上一版用纯英文合成 PDF，整份被知识库的噪声规则 symbol_ascii_only 隔离
    # （规则没错：中文语料里纯 ASCII 片段多是页眉页脚页码），切片产出 0 分块，
    # 报审因此不过——**连追四轮才发现是素材不合格**。
    #
    # 改用镜像里自带的真实标准 PDF：中文、有版面、有表格，和现场资料同构。
    # 找不到就退回合成 PDF 并在结论里标注，免得静默地测了个假东西。
    import glob as _glob
    import os as _os

    # 取**最小**的那份，不是第一份。
    #
    # 标准库里多是上百页的完整规范，MinerU 识别一份要十几分钟——
    # 探针会因此超时，而那是素材选大了，不是产品慢。
    # 最小的一份约 145 KB，几分钟内能跑完，同样是中文、有版面、有表格。
    real_samples = sorted(
        _glob.glob("/app/rules/standards/*.pdf"), key=lambda item: _os.path.getsize(item)
    )
    probe_source = "真实标准 PDF"
    if real_samples:
        with open(real_samples[0], "rb") as handle:
            pdf = handle.read()
        probe_file_name = f"写操作审计-{stamp}-{_os.path.basename(real_samples[0])}"
    else:
        probe_source = "合成 PDF（未找到真实样本，噪声规则可能整份隔离）"
        probe_file_name = f"写操作审计-{stamp}.pdf"
        stream = b"BT /F1 24 Tf 40 160 Td (AUDIT PROBE) Tj ET"
        pdf = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 220]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
            b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
            b"5 0 obj<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n"
        )
    record(
        "探针素材",
        bool(real_samples),
        f"{probe_source} {len(pdf) // 1024} KB"
        + (f" {_os.path.basename(real_samples[0])}" if real_samples else ""),
    )
    sess = api(
        f"/api/projects/{pid}/documents/upload-session",
        "contractor",
        {"files": [{"fileName": probe_file_name, "fileSize": len(pdf), "fileType": "pdf", "materialTypeCode": "manufacturing_license"}]},
    )
    sess_data = expect_ok("contractor 创建上传会话", sess, "uploadSessionId")
    doc_id = None
    if sess_data:
        session_id = sess_data["uploadSessionId"]
        urls = sess_data.get("uploadUrls") or []
        entry = urls[0] if urls else {}
        dvid = entry.get("documentVersionId") or ""
        # 生产走对象存储：uploadUrls 里是 minio 预签名地址，直接 PUT 原始字节
        put_url = entry.get("url") or ""
        put_headers = {k: v for k, v in (entry.get("headers") or {}).items()}
        put_req = urllib.request.Request(put_url, data=pdf, headers=put_headers, method="PUT")
        try:
            with urllib.request.urlopen(put_req, timeout=60) as put_resp:
                put_ok = 200 <= put_resp.status < 300
                put_msg = f"HTTP {put_resp.status}"
        except Exception as exc:  # noqa: BLE001
            put_ok, put_msg = False, str(exc)[:100]
        record("contractor 上传文件字节（预签名 PUT）", put_ok, put_msg)
        comp = api(
            f"/api/projects/{pid}/documents/upload-session/{session_id}/complete",
            "contractor",
            {"completedFiles": [{"documentVersionId": dvid, "fileSize": len(pdf)}]},
        )
        comp_data = expect_ok("contractor 完成上传会话", comp)
        if comp_data:
            doc_id = entry.get("documentId")
            record("拿到文档 ID", bool(doc_id), str(doc_id))

    binding_id = None
    if doc_id:
        bind = api(
            f"/api/projects/{pid}/documents/bindings",
            "contractor",
            {"bindings": [{"documentId": doc_id, "nodeId": node_id}]},
        )
        bind_data = expect_ok("contractor 绑定资料到节点", bind)
        if bind_data:
            affected = bind_data.get("affectedIds") or []
            binding_id = affected[0] if affected else None
            record("拿到挂载 ID", bool(binding_id), str(binding_id))

    if binding_id:
        import time as _time

        # 报审就绪要 OCR→切片→向量化三段全绿，最忠实的等法是**直接重试报审本身**。
        #
        # 重试条件按 code 判断，**不匹配提示文案**：
        # 上一版写的是「文案里没有『尚未成功』就退出」，而后来我把提示改准确了
        # （改成按卡住的环节说「文字识别还在进行中」），这个探针没跟着改，
        # 于是第一次调用就退出、报「等待 3s 仍未就绪」——
        # **探针挂在自己身上，看起来却像产品缺陷**。
        #
        # 真实素材识别要几分钟，窗口给足；超时要能分清「产品慢」和「素材选大了」，
        # 所以下面打印实际等待秒数。
        started_at = _time.time()
        deadline = started_at + 900
        sub = None
        while _time.time() < deadline:
            sub = api(
                f"/api/projects/{pid}/submissions",
                "contractor",
                {"nodeIds": [node_id], "bindingIds": [binding_id], "batchName": "写操作审计批次"},
            )
            if sub.get("code") == 0:
                break
            # 40001 是「还没就绪」这一类；其余错误码是真的失败，没必要空等
            if sub.get("code") != 40001:
                break
            _time.sleep(15)
        waited = int(_time.time() - started_at)
        if (sub or {}).get("code") == 0:
            record("contractor 正式报审（等管线就绪后）", True, f"等待 {waited}s")
        else:
            record(
                "contractor 正式报审（等管线就绪后）",
                False,
                f"等待 {waited}s 仍未就绪：{(sub or {}).get('message')}",
            )
        sub_data = (sub or {}).get("data") if (sub or {}).get("code") == 0 else None
        if sub_data:
            # 走监检**实际用的**那个接口（review-workspace），
            # 不是凭印象拼一个 /package——那个路径根本不存在，
            # 探针会因此报「检验侧看不到」，看起来像权限或数据问题。
            node_pkg = api(
                f"/api/projects/{pid}/inspection/nodes/{node_id}/review-workspace", "inspection"
            )
            record(
                "报审后检验侧能看到该节点",
                node_pkg.get("code") == 0,
                str(node_pkg.get("message") or "")[:60] or "review-workspace 可读",
            )

    expect_denied(
        "越权判据：contractor 不能写审查意见",
        api(
            f"/api/projects/{pid}/inspection/nodes/{node_id}/review-opinions",
            "contractor",
            {"opinions": []},
        ),
    )

    # ---------------- inspection：审查意见 / 退回补正 ----------------
    print("\n== inspection：审查意见 / 退回补正 ==")
    op = api(
        f"/api/projects/{pid}/inspection/nodes/{node_id}/review-opinions",
        "inspection",
        {"result": "需补正", "opinion": "写操作审计探针：需补正（探针写入，随项目一并删除）"},
    )
    expect_ok("inspection 保存审查意见", op)

    rc = api(
        f"/api/projects/{pid}/inspection/nodes/{node_id}/actions/return-correction",
        "inspection",
        {"reason": "写操作审计：退回补正探针", "bindingIds": [binding_id] if binding_id else []},
    )
    expect_ok("inspection 退回补正", rc)

    expect_denied(
        "越权判据：inspection 不能建项目",
        api("/api/projects", "inspection", {"name": "越权探针"}),
    )

    # ---------------- ndt：底片台账 ----------------
    print("\n== ndt：底片登记 / 修改 ==")
    film = api(
        f"/api/projects/{pid}/ndt/films",
        "ndt",
        {"filmNo": f"AUDIT-{stamp}-01", "weldNo": "W-AUDIT-01", "method": "RT", "nodeIds": [40]},
    )
    film_data = expect_ok("ndt 登记底片", film)
    if film_data:
        film_id = (film_data.get("film") or {}).get("id") or film_data.get("filmId")
        if film_id:
            patch = api(
                f"/api/projects/{pid}/ndt/films/{film_id}",
                "ndt",
                {"remark": "写操作审计：改一次读一次"},
                method="PATCH",
            )
            expect_ok("ndt 修改底片结论", patch)

    expect_denied(
        "越权判据：ndt 不能写审查意见",
        api(
            f"/api/projects/{pid}/inspection/nodes/{node_id}/review-opinions",
            "ndt",
            {"opinions": []},
        ),
    )

    # ---------------- owner：只读角色写必须被拦 ----------------
    print("\n== owner：只读角色，业务写必须全拦 ==")
    expect_denied(
        "owner 上传被拦",
        api(f"/api/projects/{pid}/documents/upload-session", "owner", {"files": [{"fileName": "x.pdf", "size": 10}]}),
    )
    expect_denied(
        "owner 报审被拦",
        api(f"/api/projects/{pid}/submissions", "owner", {"nodeIds": [node_id], "bindingIds": []}),
    )
    expect_denied(
        "owner 审查意见被拦",
        api(f"/api/projects/{pid}/inspection/nodes/{node_id}/review-opinions", "owner", {"opinions": []}),
    )
    owner_read = api(f"/api/projects/{pid}", "owner")
    record("owner 仍可读项目详情", owner_read.get("code") == 0)

    # ---------------- 注册申请 → 项目负责人审核（拒绝，不建账号） ----------------
    print("\n== 注册链接：匿名申请 / 负责人拒绝 ==")
    if link_data and link_data.get("token"):
        import secrets as _secrets

        probe_username = f"audit-probe-{stamp}"
        throwaway = f"Aa9!{_secrets.token_urlsafe(12)}"
        reg = api(
            f"/api/registration-links/{link_data['token']}/apply",
            "admin",  # 匿名端点，带不带 token 都行；带上不影响
            {"username": probe_username, "role": "contractor", "password": throwaway, "displayName": "写操作审计探针"},
        )
        reg_data = expect_ok("匿名提交注册申请", reg, "requestId")
        record(
            "申请阶段不建账号",
            not any(u.get("username") == probe_username for u in (api("/api/admin/users?keyword=audit-probe", "admin").get("data") or {}).get("items", [])),
        )
        if reg_data:
            rev = api(
                f"/api/projects/{pid}/registration-requests/{reg_data['requestId']}/review",
                "contractor",  # contractor 已被设为项目负责人
                {"approved": False, "reason": "写操作审计探针：例行拒绝"},
            )
            expect_ok("项目负责人（contractor）拒绝申请", rev)
            record(
                "拒绝后仍无账号",
                not any(u.get("username") == probe_username for u in (api("/api/admin/users?keyword=audit-probe", "admin").get("data") or {}).get("items", [])),
            )

    # ---------------- fde：平台写可用、业务写被拦 ----------------
    print("\n== fde：平台治理写可用 / 业务写被拦 ==")
    vc_data = None
    std = api("/api/fde/standards/vectorization?pageSize=5", "fde")
    std_files = (std.get("data") or {}).get("files") or []
    chunk = None
    kf_id = None
    for f in std_files:
        kf_id = f.get("knowledgeFileId") or f.get("id")
        if not kf_id:
            continue
        det = api(f"/api/fde/standards/files/{kf_id}/vector-detail?pageSize=1", "fde")
        rows = (det.get("data") or {}).get("chunkRows") or []
        if rows:
            chunk = rows[0]
            break
    if not chunk:
        record("fde 找到可校对知识切片", False, f"标准文件数={len(std_files)}")
    else:
        chunk_id = chunk.get("id") or chunk.get("chunkId")
        vc = api(
            "/api/fde/vector-corrections",
            "fde",
            {
                "knowledgeFileId": kf_id,
                "chunkId": chunk_id,
                "correctionType": "text",
                "after": str(chunk.get("text") or chunk.get("content") or "审计探针")[:200] or "审计探针",
                "reason": "写操作审计探针，随即自我驳回",
            },
        )
        vc_data = expect_ok("fde 创建向量修正（治理写）", vc)
    if vc_data:
        vc_id = (vc_data.get("correction") or {}).get("id") or vc_data.get("correctionId") or vc_data.get("id")
        if vc_id:
            rej = api(f"/api/fde/vector-corrections/{vc_id}/reject", "fde", {"reason": "审计探针自我驳回"})
            expect_ok("fde 驳回该修正（自清理）", rej)

    expect_denied(
        "越权判据：fde 不能做业务报审",
        api(f"/api/projects/{pid}/submissions", "fde", {"nodeIds": [node_id], "bindingIds": []}),
    )
    expect_denied(
        "越权判据：fde 不能写审查意见",
        api(f"/api/projects/{pid}/inspection/nodes/{node_id}/review-opinions", "fde", {"opinions": []}),
    )

    if link_data and link_data.get("token"):
        off = api(f"/api/projects/{pid}/registration-links/{link_data['token']}/disable", "admin", {})
        expect_ok("admin 停用注册链接", off)
        after_off = api(f"/api/registration-links/{link_data['token']}", "admin")
        record("停用后链接不可再用", after_off.get("code") != 0 or (after_off.get("data") or {}).get("usable") is False)

    return finish(pid, keep)


def finish(pid: str | None, keep: bool) -> int:
    print("\n== 收尾 ==")
    if pid and not keep:
        gone = api(f"/api/projects/{pid}", "admin", method="DELETE")
        gdata = gone.get("data") or {}
        if gdata.get("deleted"):
            check = api(f"/api/projects/{pid}", "admin")
            record("删除审计项目并确认不存在", check.get("code") != 0)
        else:
            # 有业务数据的项目删除退化为归档——这是防误删设计，本身就是一条判据
            check = api(f"/api/projects/{pid}", "admin")
            status = ((check.get("data") or {}).get("project") or {}).get("status")
            record(
                "有业务数据 → 删除退化为归档（防误删）",
                gone.get("code") == 0 and gdata.get("archived") is True and status == "已归档",
                f"status={status}",
            )
    elif pid:
        record("按 --keep 保留审计项目", True, pid)

    failed = [(s, d) for s, ok_, d in RESULTS if not ok_]
    print(f"\n共 {len(RESULTS)} 步，失败 {len(failed)} 步")
    for step, detail in failed:
        print(f"  ✗ {step}：{detail}")
    _dump_probe_status(len(RESULTS), len(failed), [s for s, _ in failed])
    return 1 if failed else 0


def _dump_probe_status(total: int, failed: int, failed_steps: list[str]) -> None:
    """探针状态落到宿主机挂载目录（/app/output 跨部署持久，/tmp 会被重建抹掉），
    供 health_watch 判「探针新鲜且全绿」——审计只在夜里跑一次，坏了没人看
    日志的话等于没跑。写不进去只打日志，不能让状态文件问题掩盖审计本身的结论。"""
    import json as _json
    import os as _os

    from libs.contracts.responses import server_time as _server_time

    try:
        _os.makedirs("/app/output/ops", exist_ok=True)
        with open("/app/output/ops/last-write-probe.json", "w", encoding="utf-8") as handle:
            _json.dump(
                {
                    "at": _server_time(),
                    "total": total,
                    "failed": failed,
                    "failedSteps": failed_steps[:10],
                },
                handle,
                ensure_ascii=False,
            )
    except OSError as exc:
        print(f"（探针状态文件写入失败：{exc}）")


if __name__ == "__main__":
    raise SystemExit(main())
