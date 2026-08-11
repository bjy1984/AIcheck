"""requirements.txt 声明的依赖必须真的装在当前环境里。

P0 审计的直接教训：本地 venv 缺 numpy / opencv-python-headless / psycopg[binary]
（三者都在 requirements.txt 里声明了），导致 test_cnse_api.py 整模块无法收集而
被静默漏跑、test_raw_vault_api 一个用例失败——装齐后立刻暴露出真实失败。

pytest 对「模块收集失败」的容忍度是零提示的：套件其余部分照常绿。这条测试把
「声明了却没装」变成显式失败，而不是让缺依赖以漏跑的形式隐身。

按 distribution 名称查 importlib.metadata，而不是尝试 import——
后者需要维护「包名 → 导入名」映射（Pillow→PIL、opencv-python-headless→cv2），
前者直接对应 requirements.txt 里写的名字。
"""
from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

REQUIREMENTS_PATH = Path(__file__).resolve().parent.parent / "requirements.txt"


def declared_distributions() -> list[str]:
    names: list[str] = []
    for raw_line in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http://", "https://")):
            continue
        # 去掉 extras（psycopg[binary]）、版本约束（>=1.26,<3）与环境标记（; python_version...）
        line = line.split(";", 1)[0]
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match:
            names.append(match.group(1))
    return names


def test_every_declared_dependency_is_installed() -> None:
    declared = declared_distributions()
    assert declared, "requirements.txt 解析出 0 个依赖——解析逻辑坏了，按失败处理"

    missing: list[str] = []
    for name in declared:
        try:
            metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(name)

    assert missing == [], (
        f"以下依赖在 requirements.txt 里声明了但当前环境没装：{missing}。"
        "缺依赖会让对应测试模块收集失败并被静默跳过——套件显示全绿但根本没跑。"
        "请执行 pip install -r requirements.txt。"
    )
