"""上传完成必须把内容哈希写回版本记录（线上审计发现）。

线上实测：一份 .docx 走完整上传流程（建会话 → **MinIO 预签名直传** → complete
code=0），文件确实落在 MinIO 里、15818 字节可取，但挂载被 40900 拒绝：
「以下资料尚未上传成功，不能挂载或提交」。

两条上传路径的差异是这个 bug 的关键：

- 经 API 中转（PUT /upload-session/.../files/{id}）——那里会写 version["hash"]，
  所以本地测试一直是绿的；
- **MinIO 预签名直传**——字节不经过 API，hash 只能在 complete 阶段补写。
  而 validate_upload_session_completion 把哈希算进了 verified 返回值，
  却从没写回 version，于是每一份走直传的文件都停在 hash=None。

document_body_uploaded() 只认 version["hash"]，直传上来的文件因此全部无法挂载。
"""

from __future__ import annotations

import pytest

import apps.api.routes as routes_module


class _FakeStorage:
    """预签名直传：complete 时才第一次向对象存储确认字节。"""

    def __init__(self, size: int) -> None:
        self.size = size

    def object_metadata(self, bucket: str, key: str) -> dict[str, object]:
        return {"size": self.size, "contentType": "application/pdf", "etag": "etag-1"}

    def content_hash(self, bucket: str, key: str) -> str:
        return CLAIMED_HASH


CLAIMED_HASH = "a" * 64
FILE_SIZE = 15818


def _direct_upload_state(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """构造「字节已在对象存储、版本记录还没有 hash」的直传中间态。"""
    version = {
        "id": "DV-DIRECT-1",
        "documentId": "DOC-DIRECT-1",
        "fileSize": 0,
        "storageKey": "documents/P/DV-DIRECT-1",
        "storageBucket": "documents",
    }
    document = {"id": "DOC-DIRECT-1", "fileName": "直传.pdf", "currentVersionId": "DV-DIRECT-1"}
    session = {
        "id": "SES-1",
        "files": [
            {
                "documentVersionId": "DV-DIRECT-1",
                "documentId": "DOC-DIRECT-1",
                "status": "待上传",  # 直传不经过 API，状态停在待上传
                "storageKey": "documents/P/DV-DIRECT-1",
                "storageBucket": "documents",
                "fileSize": 0,
            }
        ],
    }
    store = {"versions": [version], "documents": [document]}

    def _find_one(collection: str, object_id: str):
        return next((x for x in store.get(collection, []) if x.get("id") == object_id), None)

    monkeypatch.setattr(routes_module.repo, "find_one", _find_one)
    monkeypatch.setattr(routes_module, "object_storage", _FakeStorage(FILE_SIZE))
    return {"session": session, "version": version, "document": document}


def test_direct_upload_completion_writes_the_hash_to_the_version(monkeypatch) -> None:
    """这是修复点：没有它，直传文件永远 hash=None。"""
    state = _direct_upload_state(monkeypatch)
    verified, error = routes_module.validate_upload_session_completion(
        state["session"],
        {"completedFiles": [
            {"documentVersionId": "DV-DIRECT-1", "fileSize": FILE_SIZE, "contentHash": CLAIMED_HASH}
        ]},
    )
    assert error is None, error
    assert verified["DV-DIRECT-1"]["hash"] == CLAIMED_HASH
    assert state["version"].get("hash") == CLAIMED_HASH, (
        "哈希只进了返回值没写回版本——document_body_uploaded() 会判定文件未上传"
    )


def test_document_body_uploaded_accepts_the_completed_direct_upload(monkeypatch) -> None:
    """直接断言那个判据函数：它是挂载与提交的门。"""
    state = _direct_upload_state(monkeypatch)
    document, version = state["document"], state["version"]
    assert not routes_module.document_body_uploaded(document, version), "前提：完成前不该被认可"
    routes_module.validate_upload_session_completion(
        state["session"],
        {"completedFiles": [
            {"documentVersionId": "DV-DIRECT-1", "fileSize": FILE_SIZE, "contentHash": CLAIMED_HASH}
        ]},
    )
    assert routes_module.document_body_uploaded(document, version), (
        "走完整直传流程的文件仍被判为「尚未上传成功」，挂载与提交都会被 40900 拒绝"
    )
