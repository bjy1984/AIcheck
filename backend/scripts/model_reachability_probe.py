"""在线探一次「模型这条路通不通」，退出码非 0 即可挂到 cron 告警。

背景见 libs/model_reachability。2026-09-10 生产的模型密钥失效，AI 审查、一键分析、
文件分类全停，最后一次成功是 9 月 9 日 04:11——没有任何巡检发现，是人查别的事
才撞上的。

在服务器上、API 容器里跑：

    docker exec -e PYTHONPATH=/app -w /app aicheck-api \
      python3 scripts/model_reachability_probe.py

只发一次 max_tokens=1 的 ping，便宜到可以天天跑。**不打印密钥**，只打印前缀与长度，
因为这两样正是判断「配错了哪一把」最有用的信息（今天就是靠 sk-ws- 这个前缀看出
放进去的根本不是 DashScope 的密钥）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

from libs.model_reachability import probe_provider, summarize


def opener(url: str, data: bytes, headers: dict, timeout: float):
    request = urllib.request.Request(url, data=data, headers=headers)
    return urllib.request.urlopen(request, timeout=timeout).read()


def key_shape(value: str) -> str:
    return f"{value[:6]}…len={len(value)}" if value else "(未配置)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", help="只输出 JSON，供 cron 采集")
    args = parser.parse_args()

    from libs.qwen_runtime import official_api_key, qwen_runtime_config

    config = qwen_runtime_config()
    providers = [
        {
            "provider": "primary",
            "base_url": str(config.get("baseUrl") or ""),
            "api_key": official_api_key(config),
            "model": str((config.get("models") or {}).get("review") or "qwen-plus"),
        },
        {
            "provider": "vision",
            "base_url": os.getenv("AICHECK_LLM_VISION_API_BASE", ""),
            "api_key": os.getenv("AICHECK_LLM_VISION_API_KEY", ""),
            "model": os.getenv("AICHECK_LLM_MODEL_VISION", "qwen-vl-max"),
        },
    ]
    results = [
        probe_provider(
            item["provider"], item["base_url"], item["api_key"], item["model"],
            opener=opener, timeout=args.timeout,
        )
        for item in providers
    ]
    outcome = summarize(results)
    outcome["keyShapes"] = {item["provider"]: key_shape(item["api_key"]) for item in providers}
    if args.json:
        print(json.dumps(outcome, ensure_ascii=False))
    else:
        print(outcome["message"])
        for item in results:
            shape = outcome["keyShapes"].get(item["provider"])
            state = "通" if item["ok"] else f"{item['reason']}（HTTP {item['status']}）"
            print(f"  {item['provider']}: {state}  密钥={shape}")
            if item["detail"] and not item["ok"]:
                print(f"    {item['detail'][:180]}")
    return 0 if outcome["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
