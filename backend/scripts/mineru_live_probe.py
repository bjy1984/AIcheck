"""线上跑一次真实 OCR，确认 MinerU 这条路是通的。

背景：2026-08-15 查出 ocr-remote worker 里 MinerU 相关环境变量全空——
配置早写进 runtime.env，容器却揣着三天前那份。补完之后必须实测，
因为「配置加载成功」和「文件真的被识别出字」是两回事：
key 有效性、出站网络、回调解析、产物落库，任何一环断了，
表现都是资料停在「识别中」，而不是报错。

用法（在服务器上、API 容器里跑）：

    docker exec --env-file /tmp/probe.env -e PYTHONPATH=/app -w /app aicheck-api \
      python scripts/mineru_live_probe.py --base-url http://aicheck-web \
      --username 测试用户 --password-env AICHECK_PROBE_PASSWORD --file /tmp/sample.pdf

口令只经 env 传入，不进命令行——命令行会进 shell 历史和进程表。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = 60


def call(
    base_url: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict | None = None,
    method: str | None = None,
    headers: dict | None = None,
) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method or ("POST" if body is not None else "GET"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode() or "{}")


def put_bytes(url: str, data: bytes, headers: dict) -> int:
    request = urllib.request.Request(url, data=data, method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT * 5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        # 打出响应体。只报 400 而不说原因，等于把排查成本转嫁给下一个人。
        print(f"PUT 失败 HTTP {error.code}：{error.read().decode(errors='replace')[:400]}")
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-env", required=True)
    parser.add_argument("--role", default="contractor")
    parser.add_argument("--file", required=True)
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--wait-seconds", type=int, default=900)
    args = parser.parse_args()

    password = os.environ.get(args.password_env or "") or ""
    if not password:
        print(f"缺少口令环境变量 {args.password_env}")
        return 2

    login = call(
        args.base_url,
        "/api/auth/login",
        payload={"username": args.username, "password": password},
    )
    token = ((login or {}).get("data") or {}).get("token")
    if not token:
        print(f"登录失败：{json.dumps(login, ensure_ascii=False)[:200]}")
        return 2
    print(f"登录成功：{args.username}")

    project_id = args.project_id
    if not project_id:
        projects = (call(args.base_url, "/api/projects", token=token).get("data") or {})
        rows = projects.get("items") or projects.get("list") or []
        if not rows:
            print("没有可见项目")
            return 2
        project_id = str(rows[0].get("id") or rows[0].get("projectId"))
    print(f"项目：{project_id}")

    raw = open(args.file, "rb").read()
    name = os.path.basename(args.file)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    print(f"素材：{name}  {len(raw)} 字节")

    role_headers = {"X-Role": args.role}
    session = call(
        args.base_url,
        f"/api/projects/{project_id}/documents/upload-session",
        token=token,
        headers=role_headers,
        payload={
            "files": [
                {
                    "fileName": name,
                    "fileSize": len(raw),
                    "contentType": "application/pdf",
                    "materialTypeCode": "qualification_certificate",
                }
            ]
        },
    )
    data = (session or {}).get("data") or {}
    if not data.get("uploadSessionId"):
        print(f"创建上传会话失败：{json.dumps(session, ensure_ascii=False)[:400]}")
        return 1
    session_id = data["uploadSessionId"]
    entry = data["uploadUrls"][0]
    print(f"上传会话：{session_id}  条目字段：{sorted(entry.keys())}")

    url = entry["url"]
    presigned = not url.startswith("/")
    if not presigned:
        url = args.base_url.rstrip("/") + url
    # 预签名地址自带鉴权（签在 query 里），再叠 Authorization 会被 MinIO 判为
    # 「multiple authentication types」直接 400。这条我自己踩了一次：
    # 400 的正文说得清清楚楚，而我第一眼只看了状态码。
    put_headers = {
        "Content-Type": "application/pdf",
        **{k: v for k, v in (entry.get("headers") or {}).items()},
    }
    if not presigned:
        put_headers["Authorization"] = f"Bearer {token}"
        put_headers.update(role_headers)
    print(f"上传地址：{'预签名直传' if presigned else '经 API 中转'}")
    status = put_bytes(url, raw, put_headers)
    print(f"PUT 上传：HTTP {status}")

    done = call(
        args.base_url,
        f"/api/projects/{project_id}/documents/upload-session/{session_id}/complete",
        token=token,
        headers=role_headers,
        payload={
            "completedFiles": [
                {
                    "documentVersionId": entry["documentVersionId"],
                    "contentHash": digest,
                    "fileSize": len(raw),
                }
            ]
        },
    )
    if str((done or {}).get("code")) not in {"0", "200"}:
        print(f"完成上传失败：{json.dumps(done, ensure_ascii=False)[:400]}")
        return 1
    print(f"派发任务：{json.dumps((done.get('data') or {}).get('queuedTasks'), ensure_ascii=False)[:300]}")
    version_id = entry["documentVersionId"]
    document_id = str(
        entry.get("documentId")
        or ((done.get("data") or {}).get("documents") or [{}])[0].get("id")
        or ""
    )
    print(f"完成上传：版本 {version_id} 文档 {document_id or '(未回传)'}")
    if not document_id:
        print(f"完成响应：{json.dumps(done, ensure_ascii=False)[:600]}")
        return 1

    # 等识别。这里等的是**内容**，不是状态字段——状态写「已识别」而正文为空
    # 是这个系统出现过的失败形态（静默的成功），只看状态会验成全绿。
    deadline = time.time() + args.wait_seconds
    last = ""
    while time.time() < deadline:
        detail = call(
            args.base_url,
            f"/api/projects/{project_id}/documents/{document_id}",
            token=token,
        ).get("data") or {}
        # 响应是 {document, currentVersion, versions, ocrStructured, ...}，
        # 不是扁平结构。第一版探针在顶层读 ocrStatus，读到的永远是空，
        # 于是「等待超时」——而真实状态可能早就变了。看错层级和没发生，
        # 在输出上长得一模一样。
        version = detail.get("currentVersion") or {}
        document = detail.get("document") or {}
        status_text = str(version.get("ocrStatus") or document.get("ocrStatus") or "")
        if status_text != last:
            print(f"  识别状态：{status_text or '(空)'}")
            last = status_text
        structured = detail.get("ocrStructured") or {}
        fields = detail.get("extractedFields") or []
        text = str(structured.get("fullText") or structured.get("markdown") or "")
        if status_text in {"已识别", "success"}:
            print("---- 识别结果 ----")
            print(f"引擎：{version.get('ocrEngine') or structured.get('sourceEngine') or '(未标注)'}")
            print(f"正文长度：{len(text)}")
            print(f"抽取字段数：{len(fields)}")
            print(f"表格数：{len(structured.get('tables') or [])}")
            seals = structured.get("seals") or []
            print(f"印章数：{len(seals)}")
            for seal in seals[:5]:
                print(f"  印章：{seal.get('text') or seal.get('content') or seal}")
            for field in fields[:8]:
                print(
                    f"  字段：{field.get('fieldName')}"
                    f" [{field.get('reviewStatus')}] = {str(field.get('fieldValue'))[:50]}"
                )
            if text:
                print("正文前 300 字：")
                print(text[:300])
            return 0 if (text or fields or seals) else 1
        if status_text in {"失败", "failed", "识别失败"}:
            print(f"识别失败：{json.dumps(detail, ensure_ascii=False)[:600]}")
            return 1
        time.sleep(5)
    print("等待超时，仍未识别完成")
    return 1


if __name__ == "__main__":
    sys.exit(main())
