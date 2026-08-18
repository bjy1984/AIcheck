"""做向量化的组件必须拿得到 embedding 配置。

## 这条为什么值得单独立一个用例

compose 里 api 和 worker 各写了一份 embedding 配置。api 的
AICHECK_EMBEDDING_API_BASE 默认指向 embedding-service，**worker 的默认是空**
——而真正执行 embed_knowledge 的恰恰是 worker。

于是没在 .env 里显式配的部署会得到一个骗人的现场：api 看着是好的，
worker 拿到空地址 → EmbeddingClient 不启用 → 直接抛
embedding_client_not_configured → 资料永远停在「待向量化」→
document_upload_pipeline_complete 永远为假 → 施工方报审被永久拦下。

0818 线上实测就是这个形态：36 份待向量化，worker 里 8 个 embedding
环境变量全空。整条链上没有一个地方会报「配置缺了」——它只表现为
「报审点不动」，排查要从最末端一路回溯到 compose 默认值。

判据是**两边默认值一致**，不是「都非空」：两份配置指向不同的服务，
等于 api 报告的健康状态和 worker 的实际能力对不上，一样会骗人。
"""

from __future__ import annotations

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"
EMBEDDING_KEYS = (
    "AICHECK_EMBEDDING_PROVIDER",
    "AICHECK_EMBEDDING_API_BASE",
    "AICHECK_EMBEDDING_MODEL_ID",
    "AICHECK_EMBEDDING_SERVED_MODEL_NAME",
)


def _defaults_by_key(text: str) -> dict[str, list[str]]:
    """收集每个 key 出现过的所有默认值（按出现顺序）。

    不解析 YAML：这里要看的正是 `${VAR:-默认}` 里那个默认值本身，
    而 YAML 解析出来的是未展开的原串，反而绕远。
    """
    found: dict[str, list[str]] = {key: [] for key in EMBEDDING_KEYS}
    for key in EMBEDDING_KEYS:
        for match in re.finditer(rf"{key}: \$\{{{key}:-([^}}]*)\}}", text):
            found[key].append(match.group(1))
    return found


def test_embedding_默认值在各服务之间一致() -> None:
    defaults = _defaults_by_key(COMPOSE.read_text(encoding="utf-8"))
    for key, values in defaults.items():
        assert values, f"{key} 在 compose 里一处都没有——做向量化的组件会拿不到配置"
        assert len(set(values)) == 1, (
            f"{key} 在不同服务里默认值不一致：{values}。"
            "api 与 worker 必须指向同一个 embedding 服务，"
            "否则 api 看着健康、worker 实际不能向量化。"
        )


def test_embedding_地址默认值不能是空() -> None:
    """空默认值是最坏的一种：不报错，只是永远不工作。"""
    defaults = _defaults_by_key(COMPOSE.read_text(encoding="utf-8"))
    for value in defaults["AICHECK_EMBEDDING_API_BASE"]:
        assert value.strip(), (
            "AICHECK_EMBEDDING_API_BASE 默认为空——没显式配置的部署里，"
            "资料会永远停在「待向量化」，而没有任何一处会说配置缺了"
        )
