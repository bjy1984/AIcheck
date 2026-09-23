# Jev 原子题、R19 与决策报告准备（2026-09-23）

七项目私有快照额外保存**本地** ReviewRun、规则结果和人工修正，以便冻结输入与
离线对照。这些记录不进入 Jev 请求；文件归属预检只读取文件、版本与 OCR。
`run_jev_atomic_evaluation.py` 对有冻结业务包与实际规则结果的正式任务提取固定
原子题，只发完整当前 OCR 与题目。R19 用 `--mode r19` 另跑八题适用性／满足性
问题，与当前 Qwen 结果比较，不混入规则引擎 16＋17 风险样本。节点 24／29
的多人题暂不纳入该原子题回放，报告列出排除数量，不借通用题冒充逐人评估。

轮换测试密钥到位后，先不加 `--send` 预检，再按精确请求上限小批实跑。
以下 `N` 必须换成该批刚预检得到的精确请求数：

```bash
cd backend
.venv/bin/python -m scripts.run_jev_atomic_evaluation \
  --snapshot /private/path/seven-project.json.zlib --limit 2 --max-requests N \
  --expected-requests N \
  --send --output /private/path/atomic-run.json
.venv/bin/python -m scripts.run_jev_atomic_evaluation \
  --snapshot /private/path/seven-project.json.zlib --mode r19 \
  --limit 2 --max-requests N --expected-requests N \
  --send --output /private/path/r19-run.json
```

`prepare_jev_atomic_labels.py` 从实际影子记录生成盲标题包。默认抽 16 道规则分歧
及 17 道 Jev 判通过题；`--comparison r19` 则输出独立 R19 题包。监检人员只见
原子项、文件版本和固定题目，不见 Jev 或既有结论。填写人、四态选择及哈希核对后，
`evaluate_jev_atomic_opinions.py` 分别计算两组准确率和错误通过。

`compile_jev_decision_report.py` 可从三组实跑记录、两套独立标注及供应商账单记录
重算元数据报告。缺实际调用、33 题、28 份文件真值、R19 标注或账单时明确输出
`incomplete` 与阻塞项；即便齐全也只为 `ready_for_decision`，不自动批准门槛、
拒绝主张、文件挂载或正式裁决。33 题是风险抽样，不可说成全体准确率。

本环境当前仍没有新测试密钥，监检标注亦未到位；三组实际 Jev 调用均为 0。
七项目快照已取得，但本次历史任务中原子题 12 个候选全部因资料指纹变化或
全文超长而停下；R19 无可对照正式任务。详见
[`新快照与中间报告`](2026-09-23-jev-fresh-snapshot-interim-report.md)。

本机运行报告编译器得到 `incomplete`，阻塞项为三组实际调用、文件归属真值、
33 题真值、R19 真值及供应商账单；私有 JSON 在
`/Users/big67/.codex/aicheck-jev-eval/2026-09-23/aicheck-jev-decision-single-interim-20260923.json`
（0600）。此前完整后端测试
**5,473 通过、81 跳过、0 失败**，Ruff 基线 **286／286**，`git diff --check`
通过。81 项环境选择性跳过不算外部服务实测。
