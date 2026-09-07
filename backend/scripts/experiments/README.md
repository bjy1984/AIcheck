# 审查基准（P8 H0）

三个脚本，全部**不落库**，只在生产容器里手动跑（需要真实 OCR 快照与模型密钥）：

| 脚本 | 作用 | 固定样本 |
|---|---|---|
| `review_model_compare.py` | 克隆已完成的 AiRun，重建证据分片，跑完整节点审查图，记录 §11.1 与 §17.3 指标 | 测试项目4 节点 24（1 片）、测试项目3 节点 2（多片） |
| `pa_model_compare.py` | 一键分析同一请求发多个模型，用生产校验器校验 | 测试项目4 节点 1/2/16/24 一批 |
| `summarize.py` | 汇总 `out/<date>/` 为 Markdown 与 JSON | — |

```bash
# 在 aicheck-api 容器里
for m in qwen3.8-max qwen3.7-plus qwen-plus qwen-flash qwen3-30b-a3b-instruct-2507; do
  AICHECK_LLM_MODEL_REVIEW=$m PYTHONPATH=/app python3 scripts/experiments/review_model_compare.py
done
PYTHONPATH=/app python3 scripts/experiments/pa_model_compare.py --models qwen3.8-max,qwen3.7-plus,qwen-plus
PYTHONPATH=/app python3 scripts/experiments/summarize.py
```

费用约每轮 ¥10（六模型，按系统单价折算，真实账单以阿里云为准）。频次：每个子阶段合并前一轮、灰度期间每天一轮。

指标含义：
- 通过守卫 = `groundingStatus == grounded` 的发现数；模板标题 = 标题以"证据不足，需人工确认"开头的发现数。
- 失败分片 / 信封错误 = 分片状态 failed / 模型返回没有 `findings` 数组。
- 摘要为模板 = `suggestion.opinionDraft` 是守卫模板句（P9 R2 目标为 0）。
- 正文>150 = description 超过 150 字的发现数（P9 R3 目标 ≤5%）。

改脚本前先读 `review_model_compare.py` 顶部的两处坑。`out/` 不进仓库。
