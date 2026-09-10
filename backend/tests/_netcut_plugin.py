"""跑测试时掐掉网络：任何真的去连网的代码会当场炸。

在 fixture 里替换而不是在模块顶层：import 期间替换 socket.socket 会让 ssl 炸掉
（SSLSocket 继承 socket），那是工具坏了，不是被测代码坏了。
"""
import socket

import pytest


class NetworkAttempted(AssertionError):
    pass


@pytest.fixture(autouse=True)
def _cut_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise NetworkAttempted("测试期间尝试建立网络连接")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield
