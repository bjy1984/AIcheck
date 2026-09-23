# Jev 实测与监检标注准备（2026-09-23）

`run_jev_routing_evaluation.py` 是测试资料的**只读**文件归属评估入口。默认只
预检；实际调用必须加 `--send`，并在独立测试进程提供轮换后的
`AICHECK_JEV_API_KEY`、`AICHECK_JEV_ENABLED=true`、
`AICHECK_JEV_DATA_EGRESS_APPROVED=true`。它不读取旧 `JEV_KEY`，不写
文件挂载、审查结论或生产状态。`--max-requests` 在首个外呼前对整批检查，
结果输出文件也先以 0600 权限预留。模型仍固定 `jev-1.13.0`。

本地实跑前的无网络预检：`test2/` 20 份中 **19 份可发起、1 份超长**，
全量预计 **66 次请求**。默认前两份预计 6 次；指定原先测试的
`test2-019`／`test2-020` 预计 8 次。以上实际请求数均为 **0**。
七项目上次只读快照为 178／194 份可发起、预计 546 批；私有 OCR 快照已
按当时约定删除，不能把这个估算写成已经完成的本轮实测。

小批实测命令（输出路径须是尚不存在的私有文件）：

```bash
cd backend
.venv/bin/python -m scripts.run_jev_routing_evaluation \
  --test2 --case-id EVAL-test2-019 --case-id EVAL-test2-020 \
  --limit 2 --max-requests 10 --send \
  --output-shadows /private/path/test2-jev-shadows.jsonl \
  --output-report /private/path/test2-jev-report.json
```

七项目则把 `--test2` 换成 `--snapshot /private/path/seven-project.json.zlib`，
先小批、复核结果后再增加 `--limit` 和显式请求上限。快照必须是之前定义的
`read_only_seven_project_ocr_snapshot` 且权限 0600；脚本先验证工程／版本／
连结边界。输出只有 ID、状态、节点选择和把握值，不含 OCR 或密钥，可直接交给
现有文件归属标注评估脚本。超长、OCR 未完成及预算超限各有状态，不截断原文。

统一 Jev 客户端新增可选的数字用量观察回调，只记录每批时长、成功／失败状态、题数及 API 若有
提供的 token／美元用量。API 没提供费用时明确返回 `not_reported_by_api`，
需以供应商账单核对，不能套用旧的每轮估算。

旧研究提到的 33 题原件找不到。`evaluate_jev_atomic_opinions.py` 可从后续影子
运行的私有**元数据**快照（`review_runs` 与 `rule_check_results`，不含 OCR）
重新抽取 16 道高把握分歧及 17 道较低把握的 Jev「通过」候选；R19 与 Qwen
语义结果的对照不混入规则引擎样本，缺少实际落库规则结果的题也不入选。不足 33 道就
报告 `insufficient_candidate_pool`，不补造旧题。每题携带任务 ID、输入哈希、
文件版本和建议支持页。监检人员独立标注后，以同一脚本比较 Jev 与现有结果的
准确率、错误通过及阈值扫描；输入哈希不一致的标注不计入。报告始终保持
`releaseThresholdApproved=false`。文件归属另用现有独立标注格式，不拿旧挂载当真值。

本环境当前没有轮换后的测试密钥，也没有监检标注；因此**尚无新的实际 Jev
调用、准确率或费用**。本批只完成可重复的调用／评估路径和离线预检。

验证：完整后端测试 **5,454 通过、81 跳过、0 失败**；
Ruff 基线 **286／286**，`git diff --check` 通过。81 条环境选择性跳过
不算 PostgreSQL、MinIO、Temporal 的本批服务实测。
