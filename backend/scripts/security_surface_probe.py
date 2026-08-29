"""安全攻击面探针（每日巡检）。

单测 test_security_hardening 覆盖认证/口令面 16 项；这里补的是**攻击者会试的动作**，
且打真实生产 API：路径穿越、上传类型绕过、越权读取、注入面、幂等重放、
大载荷、匿名/伪造 token。

判据必须看信封码：本系统 HTTP 200 + body.code 表达业务错误，
只看 HTTP 状态码会把「已拦截」误判成「放行」——本探针第一版就栽在这，
差点报出两个不存在的高危。

状态文件落 /app/output/ops/，由 health_watch 判「新鲜且全绿」。

## 用法

    docker exec aicheck-api python3 /app/scripts/security_surface_probe.py
"""

import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/scripts")
from write_ops_audit import BASE, api, record, RESULTS, token_for, USERS  # noqa: E402

PID = "P-2026-HDCP-001"


def envelope_code(body: str) -> int | None:
    """信封式响应的业务码。本系统 HTTP 200 + body.code 表达业务错误——
    只看 HTTP 状态码会把「已拦截」误判成「放行」（本探针第一版就栽在这）。"""
    try:
        return int(json.loads(body).get("code"))
    except (ValueError, TypeError, AttributeError):
        return None


def rejected(status: int, body: str) -> bool:
    """被拒 = HTTP 401/403，或信封码为非零（401/403/40xxx）。"""
    if status in {401, 403}:
        return True
    code = envelope_code(body)
    return code is not None and code != 0


def raw_call(path: str, role: str, method: str = "GET", body: bytes | None = None,
             headers: dict | None = None) -> tuple[int, str]:
    """不经 api() 的原始调用：需要看真实 HTTP 状态码与信封码。"""
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token_for(role)}",
            "Content-Type": "application/json",
            "X-Role": role,
            "X-User-Id": USERS[role][1],
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2000).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{exc.__class__.__name__}: {exc}"


# ---- 1. 路径穿越：上传会话的 fileName / relativePath ----
traversal_names = [
    "../../../etc/passwd",
    "..\\..\\windows\\system32\\config\\sam",
    "normal/../../escape.pdf",
    "a\x00b.pdf",
]
escaped = []
for name in traversal_names:
    resp = api(
        f"/api/projects/{PID}/documents/upload-session", "contractor",
        {"files": [{"fileName": name, "fileSize": 1024, "fileType": "pdf"}]},
    )
    # 判据看**落盘路径**（storageKey / url），不看回显的 fileName——
    # 回显原样是正常的（前端要展示用户输入），真正危险的是写到哪。
    stored = ""
    if resp.get("code") == 0:
        urls = (resp.get("data") or {}).get("uploadUrls") or []
        entry = urls[0] if urls else {}
        stored = f"{entry.get('storageKey') or ''}|{str(entry.get('url') or '').split('?')[0]}"
    if ".." in stored or "\x00" in stored or "/etc/" in stored or "system32" in stored.lower():
        escaped.append(f"{name!r}→{stored[:100]}")
record("路径穿越：上传文件名被消毒", not escaped, "; ".join(escaped) or f"{len(traversal_names)} 种穿越写法全部消毒")

# ---- 2. 上传类型绕过：可执行/脚本类扩展名 ----
bad_types = [("evil.sh", "application/x-sh"), ("evil.exe", "application/octet-stream"),
             ("evil.html", "text/html"), ("evil.pdf.exe", "application/octet-stream")]
accepted = []
for name, ctype in bad_types:
    resp = api(
        f"/api/projects/{PID}/documents/upload-session", "contractor",
        {"files": [{"fileName": name, "fileSize": 1024, "fileType": ctype}]},
    )
    if resp.get("code") == 0:
        accepted.append(name)
record("上传类型白名单：可执行/脚本被拒", not accepted, f"被接受的危险类型：{accepted}" if accepted else "4 种全部拒绝")

# ---- 3. 越权：施工方读 AI 判定 / 跨项目读取 ----
status, body = raw_call(f"/api/projects/{PID}/inspection/nodes/24/review-workspace", "contractor")
record("越权：施工方读监检工作台被拒", rejected(status, body), f"HTTP {status} code={envelope_code(body)}")

other = api("/api/projects", "admin")
other_ids = [
    str(item.get("id"))
    for item in ((other.get("data") or {}).get("items") or [])
    if str(item.get("id")) != PID
][:1]
if other_ids:
    status, body = raw_call(f"/api/projects/{other_ids[0]}/documents", "contractor")
    # 该施工方不是这个项目的成员：必须被拒，返回 200+数据即越权
    record("越权：非成员跨项目读取被拒", rejected(status, body),
           f"HTTP {status} code={envelope_code(body)}（项目 {other_ids[0]}）")

# ---- 4. 注入面：关键词参数带 SQL/JSONB 元字符 ----
injections = ["' OR 1=1--", '"; DROP TABLE aicheck_state;--', "{\"$ne\": null}", "%27%20OR%201=1"]
broken = []
for payload in injections:
    status, body = raw_call(f"/api/projects?keyword={urllib.request.quote(payload)}", "admin")
    if status >= 500 or "syntax error" in body.lower() or "psycopg" in body.lower():
        broken.append(f"{payload!r}→HTTP {status}")
record("注入面：关键词元字符不触发后端异常", not broken, "; ".join(broken) or f"{len(injections)} 种注入串全部安全处理")

# ---- 5. 幂等重放：同 key 不同 body ----
key = "PENTEST-REPLAY-1"
first = api(f"/api/projects/{PID}/documents/upload-session", "contractor",
            {"files": [{"fileName": "replay-a.pdf", "fileSize": 100, "fileType": "pdf"}]},
            extra_headers={"Idempotency-Key": key})
second = api(f"/api/projects/{PID}/documents/upload-session", "contractor",
             {"files": [{"fileName": "replay-b.pdf", "fileSize": 999, "fileType": "pdf"}]},
             extra_headers={"Idempotency-Key": key})
# 判据：同 key 不同 body 必须冲突（40009 之类），不得静默返回首次结果或执行第二次
conflict = second.get("code") != 0
record("幂等：同 key 不同 body 被拒", conflict, f"first={first.get('code')} second={second.get('code')} msg={str(second.get('message'))[:60]}")

# ---- 6. 大载荷：超大 JSON 不得打垮进程 ----
huge = json.dumps({"files": [{"fileName": "x.pdf", "fileSize": 1, "fileType": "pdf", "pad": "A" * 2_000_000}]}).encode()
status, _ = raw_call(f"/api/projects/{PID}/documents/upload-session", "contractor", "POST", huge)
record("大载荷：2MB 请求被拒或安全处理", status in {400, 413, 422, 200} and status != 0, f"HTTP {status}")

# ---- 7. 无 token / 伪造 token ----
def unauthenticated(headers: dict) -> tuple[int, str]:
    req = urllib.request.Request(f"{BASE}/api/projects", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(500).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(500).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


anon_status, anon_body = unauthenticated({"Content-Type": "application/json"})
record("匿名访问被拒", rejected(anon_status, anon_body),
       f"HTTP {anon_status} code={envelope_code(anon_body)}")

forged_status, forged_body = unauthenticated({
    "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZG1pbiJ9.forged",
    "X-Role": "admin",
    "X-User-Id": "USER-ADMIN-001",
})
record("伪造 token 被拒", rejected(forged_status, forged_body),
       f"HTTP {forged_status} code={envelope_code(forged_body)}")

failed = [(s, d) for s, ok_, d in RESULTS if not ok_]
print(f"\n共 {len(RESULTS)} 项，失败 {len(failed)}")
for s, d in failed:
    print(f"  ✗ {s}：{d}")

try:
    import os as _os

    from libs.contracts.responses import server_time as _server_time

    _os.makedirs("/app/output/ops", exist_ok=True)
    with open("/app/output/ops/last-security-probe.json", "w", encoding="utf-8") as handle:
        json.dump(
            {
                "at": _server_time(),
                "total": len(RESULTS),
                "failed": len(failed),
                "failedSteps": [step for step, _ in failed][:10],
            },
            handle,
            ensure_ascii=False,
        )
except OSError as exc:
    print(f"（探针状态文件写入失败：{exc}）")

raise SystemExit(1 if failed else 0)
