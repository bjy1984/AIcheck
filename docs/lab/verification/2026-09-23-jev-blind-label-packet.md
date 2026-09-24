# Jev 文件归属盲标题包（2026-09-23）

`backend/scripts/prepare_jev_routing_labels.py` 从新七项目私有 OCR 快照中，按固定
哈希种子在**看到 Jev 答案之前**每项目抽四份完整可处理文件。每份列出全部可用
节点和空白「属于／不属于／不确定」栏，保存文件版本及实际 Jev 请求输入哈希。
题包不包含 Jev 的选择／把握值，也不包含现有挂载。另有私有来源包，逐份提供
完整 OCR 与固定节点题目供监检员查阅；来源包和空白标注表分开保存。

标注人填写 `annotatedBy` 和每个 `nodeLabels[].choice`，可用值是
`belongs`、`does_not_belong`、`uncertain`。`expectedNodeIds` 不得删改；漏标
直接报错。标注完成后，原 `evaluate_jev_document_routing.py --labels` 可直接读取
此 JSON 题包，并只在工程／文件版本／输入哈希相同且影子状态为 completed 时
计算精确率、召回率和 Wilson 95% 区间。该区间按节点对计算，未建模同一文件内
节点结果的相关性；报告必须同时注明样本是 28 份文件而不是全部 194 份。

生成命令（新文件必须位于私有工作目录，权限 0600）：

```bash
cd backend
.venv/bin/python -m scripts.prepare_jev_routing_labels \
  --snapshot /private/path/seven-project.json.zlib \
  --output /private/path/jev-routing-inspector-packet.json
```

新快照已取得，真实题包为 28 份文件、1,904 个节点配对；监检标注目前仍为 0。
私有路径、快照哈希及来源包见
[`新快照与中间报告`](2026-09-23-jev-fresh-snapshot-interim-report.md)。录制测试验证
固定抽样、空白题包、不泄露预测／旧挂载、版本哈希与完整节点检查。
