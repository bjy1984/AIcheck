# Jev 文件归属离线评估（2026-09-23）

本分支已有异步、影子模式的文件归属建议，但尚无监检确认的文件到节点真值集。`test2/`
的 20 份 OCR 目前只完成请求容量预检：19 份可发起，1 份超过 40,000 字而跳过；
没有据此测出归属准确率，也没有把建议用于自动挂载。

本批新增 `backend/scripts/evaluate_jev_document_routing.py`，只读本地 JSONL，不调用
Jev 或其他外网服务。它按工程、文件、**文件版本**精确匹配影子输出与监检标注；
未标注节点不视为负例。`partial`、超长、不可用等非完成结果，以及仅由系统预标的
`provisional` 标注，只计入覆盖情况，不计入准确率。报告不包含 OCR 原文，保留
案例和节点 ID 以便人工复核。

影子输入每行是一份文件的 `jevRoutingShadow` 对象，例如：

```json
{"projectId":"P1","documentId":"D1","documentVersionId":"V1","status":"completed","nodeScores":[{"nodeId":25,"choice":"yes","confidence":0.94},{"nodeId":26,"choice":"no","confidence":0.92}],"suggestedNodeIds":[25],"existingNodeIds":[25],"humanRejectedNodeIds":[]}
```

标注输入每行对应同一个版本，由监检人员独立判断每个**已标**节点的归属：

```json
{"projectId":"P1","documentId":"D1","documentVersionId":"V1","labelSource":"inspector","annotatedBy":"inspector-01","nodeLabels":[{"nodeId":25,"choice":"belongs"},{"nodeId":26,"choice":"does_not_belong"}]}
```

`choice` 可以是 `belongs`、`does_not_belong` 或 `uncertain`。不确定题不进入精度分母；
每个版本只能有一份标注。多人独立标注时应先保留各自原件并完成人工裁定，再输入
该文件。影子输出需要从本工程当前版本的存储记录中导出，不能把跨工程或过期版本
拼在一起；只导出 `jevRoutingShadow`，不要把原始 OCR 放入评估文件。

在 `backend/` 目录运行：

```bash
.venv/bin/python -m scripts.evaluate_jev_document_routing \
  --shadows /path/to/shadows.jsonl \
  --labels /path/to/inspector-labels.jsonl \
  --threshold 0.90 \
  --output /path/to/routing-report.json
```

报告分别列出 Jev 建议和现有节点挂载相对同一批标注的精确率、召回率及逐题差异，
并显示 0.60–0.95 的阈值扫描。现有挂载只是对照，不保证本身正确。缺少分数的题按
弃答处理；监检认为应归属、系统却留有人工拒绝记录时另计冲突，须先查清标注或版本。
没有可比的监检标注时脚本以状态 `no_comparable_inspector_labels` 及退出码 2 提醒，
不会输出一个看似有效的准确率。任何报告都固定 `releaseThresholdApproved: false`；
阈值扫描只是供监检复核，不会自动开启发布开关。

这份文件归属真值集与原计划中「16 道规则分歧 + 17 道 Jev 判通过」的 33 道原子项
标注是两项不同工作。前者决定能否让 Jev 参与文件归属，后者决定逐句核对、第二意见
和队列阈值；两者都不能用合成数据或旧挂载直接代替人工真值。
