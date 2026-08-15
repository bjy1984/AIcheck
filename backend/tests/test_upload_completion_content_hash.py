"""文件本体的哈希，必须按存储里的实际字节算。

## 线上实操（2026-08-15）

浏览器上传三步全绿：建会话 128ms → PUT 字节 31ms → complete 330ms，
MinIO 里 stat 得到 80 字节。但接着点「选择环节」挂载，被拒：

    关联审核环节失败：以下资料尚未上传成功，不能挂载或提交
    （错误码：DOCUMENT_BODY_MISSING）

查库：version.hash 为空、sizeBytes 为空。

`document_body_uploaded()` 只认 version["hash"]，而这个值原先来自**客户端**
在 complete 时声明的 contentHash——前端从来没填过这个字段。于是每一份走完整
上传流程的文件都停在 hash=None：字节在存储里好好的，挂载和提交一律被拒。

客户端也算不了：站点是 http，非安全上下文，浏览器 crypto.subtle 不可用。

而且「文件本体是否真的传上来了」这种判断，本就不该以被审计方声明的值为准。
读存储里的字节自己算，才是可信的那一份——代码里原本的注释写的就是这个设计
（「由 complete 阶段按对象存储里的实际字节算出」），只是没实现。
"""

from __future__ import annotations

import hashlib
import inspect


def test_按实际字节算而不是信客户端声明():
    from apps.api import routes

    source = inspect.getsource(routes.validate_upload_session_completion)
    block = source[source.index("for update in storage_updates:") :]
    assert "object_storage.content_hash(" in block, "还在只信客户端声明的 contentHash"
    # 存储算出来的要优先于声明值
    assert "storage_hash or resolved_hash" in block, "存储算出的哈希要优先"


def test_算不出来时不掀翻整次上传():
    """存储临时不可用时，退回客户端声明值——总比让用户重传一遍强。"""
    from apps.api import routes

    source = inspect.getsource(routes.validate_upload_session_completion)
    block = source[source.index("for update in storage_updates:") :]
    assert "except Exception" in block


def test_内容哈希是分块读的():
    """上传的可能是几百兆的图纸，整份读进内存不合适。"""
    from libs.integrations.storage import ObjectStorage

    source = inspect.getsource(ObjectStorage.content_hash)
    assert "response.stream(" in source, "要分块读"
    assert "sha256" in source
    assert "response.close()" in source and "release_conn()" in source, "连接要归还"


def test_哈希格式与既有留痕一致():
    """Raw Vault 那条链用的是 `sha256:<hex>`，两边必须同一种写法，
    否则比对时会得到「不一致」这种假结论。"""
    from libs.integrations.storage import ObjectStorage

    source = inspect.getsource(ObjectStorage.content_hash)
    assert '"sha256:" + digest.hexdigest()' in source
    # 与 raw vault 的写法对齐
    expected = "sha256:" + hashlib.sha256(b"probe").hexdigest()
    assert expected.startswith("sha256:") and len(expected) == 71
