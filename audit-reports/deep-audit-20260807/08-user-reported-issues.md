# 用户反馈问题确认（2026-08-11）

对用户提出的 6 项问题逐条实测确认。**全部属实**，其中 2 项比原描述更严重。
本轮只确认，未改代码。

---

## U-1 · 公章检测与 MinerU 在线 OCR 均未启用 【P1·配置】

**公章检测两条管线都是关闭的**（`backend/.env`）：

```
AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE=false
AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR=false
AICHECK_SEAL_DET_MODEL_DIR=...     ← 模型路径已配，但管线关着
AICHECK_SEAL_REC_MODEL_DIR=...
```

**MinerU 完全没有配置**：`.env` 中不存在 `MINERU_API` / `MINERU_TOKEN` 等任何凭证，
而 [tasks.py:1462-1470](../../backend/apps/worker/tasks.py) 的默认 provider 恰恰是 `mineru`：

```python
return (configured or "mineru").lower()
```

即：**系统默认走 MinerU，但没有可用凭证**——在线 OCR 转换必然失败。

业务影响：公章是监检判定的关键证据（业务规则里明确要求「印章名称只允许正式名称一致
或已审核别名匹配」）。管线关闭时 `recognize_signatures_and_seals` 仍返回
`status: succeeded`，只是 `signatureCount: 0` —— **失败表现为「没有印章」而非「未检测」**，
判定链会据此认为资料缺少印章。

### 更正与修复（2026-08-11）

**关于 MinerU 的判断有误，在此更正**：`load_mineru_config` 本就带凭证校验，
无 API Key 时抛 `MINERU_NOT_CONFIGURED`，**失败是显式的、不是静默的**。
原文「在线 OCR 转换必然失败」属实（默认 provider 是 mineru 而配置缺凭证），
但「静默失败」的定性错误。用户已提供 MinerU 凭证，配置补齐即可。

**公章部分属实且已修**（提交 `4d7222c`）：
- `recognize_document_seals` 在管线全关时返回 `status: capability_disabled`、
  `sealCount: None`（而非 0），并列出各管线开关状态；
- `recognize_signatures_and_seals` 向上透传该状态；
- 聚合器新增 `capability_disabled → evidence_insufficient` 分支。

修复前实测漏洞：`capability_disabled` 与其他工具的 `passed` 同在时，
**整体判为 `passed`** —— 即「印章没查」被当成通过。修复后为 `evidence_insufficient`；
真实的 `failed` 仍优先。管线启用后 `sealCount: 0` 重新成为可信结论。

**本地无法启用公章管线**：模型盘 `/Volumes/7up/aicheck-ocr-models/official_models`
未挂载，`PP-OCRv4_server_seal_det` 等模型不可用；`agentdesign` 后端路径同样不存在。
启用需要先挂载模型盘。

---

## U-2 · 点击业务节点后加载缓慢 【P1】

实测单次点击节点触发的请求（本地直连，无网络延迟）：

| 请求 | 耗时 | 响应体积 |
|---|---|---|
| standards | **1223 ms** | 7,834 字符 |
| audit-overview | 324 ms | 913,873 |
| package | 92 ms | **689,862** |
| tree | 68 ms | 775,316 |
| audit-workspace | 66 ms | **1,717,218** |
| ai-runs | 25 ms | 664,847 |
| review-opinions / date-compare | 各 2 ms | 少量 |
| **合计** | **1801 ms** | **约 4.7 MB JSON** |

**本地无网络延迟即 1.8 秒；生产经公网会显著放大。**

体积构成（谁在撑大响应）：

```
package.aiRuns              664,847 字符 / 9 条   ← 全量 AI 运行历史，不分页
audit-workspace.content   1,307,897 字符 / 7 项
audit-workspace.project     393,908 字符          ← 与其他请求重复传输
```

即：节点包里塞进了**全部历史 AI 运行记录**，且 `project` 在多个响应里重复下发。

---

## U-3 · 处理状态暴露技术过程 【P2】

[documentPipelineStatus.ts](../../frontend/src/utils/documentPipelineStatus.ts) 对施工方展示：

```
排队中 → OCR 中 → 待切片 → 切片中 → 待向量化 → 向量化中 → 已完成
```

`切片`、`向量化` 是 RAG 内部实现细节，施工方无从理解，也不需要理解。

**用户期望**：上传中 → 上传成功（可提交）。

---

## U-4 · 提交等关键动作无确认弹窗 【P2】

施工方主提交路径 [`handleSubmitBatch`](../../frontend/src/views/AICheck/Workbench.vue)（3335 行）
**直接调用提交接口，无任何确认**。

全文件仅 3 处 `ElMessageBox`：
- 3114 行：删除文件（有确认）
- 3672 / 4094 行：两处 prompt 输入

即：**删除文件有确认，正式提交资料给监检机构反而没有**。提交是不可逆的业务动作
（提交后进入监检审查流程，撤回需走专门接口），风险高于删除未提交文件。

打回、采纳 AI 建议等动作同样无确认。

---

## U-5 · 无重试按钮；上传失败仍可提交 【P1·比原描述更严重】

**无重试入口**：全文件搜索「重试」只出现在错误提示文案里
（「请刷新后重试」「请稍后重试」），**没有任何重试按钮**——用户只能刷新页面重来。

**提交按钮不校验上传状态**：
[SubmissionBatchDialog.vue:287](../../frontend/src/views/AICheck/components/SubmissionBatchDialog.vue)
的禁用条件只有 `:disabled="!bindings.length"`（有没有勾选资料），
**完全不看资料的处理状态**。

### 实测：空壳资料可以走完整个提交流程

```
1. 创建上传会话，从不 PUT 任何内容        → 文档 DOC-3E272F59
2. 挂载到节点 24                          → code 0，BIND-24-63BF66
3. 提交给监检                              → code 0
4. 监检人员看到：上传失败的资料2.pdf  状态=已提交
```

**一份从未上传成功、没有任何内容的文件，被成功提交并进入监检审查流程**，
在监检人员的台账里显示为正常的「已提交」资料。

这比「按钮可点击」严重：不是 UI 没拦住，而是**整条链路（挂载→提交→审查）都没有校验文件本体是否存在**。
与 M-4（空壳文档进台账）同源，但危害升级——M-4 只是出现在列表里，这里是进入了审查流程。

---

## U-6 · 监检页面频繁整体自动刷新 【P1】

[Workbench.vue:416-417](../../frontend/src/views/AICheck/Workbench.vue) 两个轮询定时器：

```javascript
const REVIEW_POLL_INTERVAL_MS = 5000               // 5 秒
const POST_UPLOAD_PIPELINE_POLL_INTERVAL_MS = 10000 // 10 秒
```

**两者都调用 `loadNodePackage()`** —— 即 U-2 中那个 **665 KB** 的全量节点包接口，
且是整体替换数据，导致页面整体重绘。

```javascript
// 5 秒轮询
void refreshAiReviewStatus()  → await loadNodePackage(activeNodeId.value, { silent: true })
// 10 秒轮询
void refreshPostUploadPipelineStatus() → await loadNodePackage(activeNodeId.value, { silent: true })
```

即：**AI 复核期间每 5 秒重新拉取并整体替换 665 KB 数据**，上传后叠加 10 秒一次。
用户感知到的「页面频繁整体刷新」正是这个。

（`silent: true` 只抑制 loading 态，不影响数据整体替换与重绘。）

对照 AI 复核 B 版工作台还有一个 **400 ms** 的轮询
（`ConversationalReviewWorkbenchB.vue:461`），间隔更激进。

---

## 汇总

| # | 问题 | 级别 | 确认结论 |
|---|---|---|---|
| U-1 | 公章检测 + MinerU | P1 | 公章属实**已修**（4d7222c）；MinerU「静默失败」的定性有误，已更正——它会显式报 MINERU_NOT_CONFIGURED |
| U-2 | 节点加载缓慢 | P1 | 属实**已修**（da6f14d）——1801ms → 831ms（-54%）|
| U-3 | 状态显示技术过程 | P2 | 属实**已修**（da6f14d）——提交方改为 上传中/上传成功/上传失败 |
| U-4 | 无提交确认弹窗 | P2 | 属实**已修**（da6f14d）——提交/打回/采纳建议均加确认 |
| U-5 | 无重试 + 失败仍可提交 | P1 | 属实且更严重，**已修**（406a332）——挂载/提交三入口按内容哈希校验 |
| U-6 | 页面频繁整体刷新 | P1 | 属实——5 秒/10 秒轮询各拉一次 665 KB 全量包 |

**关联既有发现**：U-5 与 M-4 同源（空壳文档），U-2 与 U-6 同源
（`package` 接口过重 + 高频全量轮询，互相放大）。
