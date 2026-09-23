# Jev 文件归属盲标题包（2026-09-23）

`backend/scripts/prepare_jev_routing_labels.py` 从新七项目私有 OCR 快照中，按固定
哈希种子在**看到 Jev 答案之前**每项目抽四份完整可处理文件。每份列出全部可用
节点和空白「属于／不属于／不确定」栏，保存文件版本及实际 Jev 请求输入哈希。
题包不包含 Jev 的选择／把握值，也不包含现有挂载。OCR 原文继续由监检人员
在内部文件界面读取，题包不复制正文。

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

当前七项目新快照尚未取得，所以本批**未生成真实题包，也没有监检标注**。
录制测试验证了固定抽样、空白题包、不泄露预测／旧挂载、版本哈希与完整节点检查。
