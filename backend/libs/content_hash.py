"""内容哈希的归一化。

两边格式本来就不一致：经 API 中转的上传写入 "sha256-<hex>"，而客户端
（以及直传路径）算的是裸 <hex>。原先那条一致性校验因为字段名错配从没生效，
这个差异一直被掩盖着；一旦校验开始工作，每次上传都会误报「哈希不一致」。

从 routes.py 下沉到这里（issue #12 A-2）：它是纯函数、无依赖，
路由拆分时不该跟着复制一份。
"""

from __future__ import annotations

from typing import Any

_HASH_PREFIXES = ("sha256-", "sha256:")


def normalized_content_hash(value: Any) -> str:
    """把内容哈希归一到纯十六进制，便于比较。"""
    text = str(value or "").strip().lower()
    for prefix in _HASH_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):]
    return text
