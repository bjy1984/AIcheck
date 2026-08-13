# 线上审计（2026-08-13）

环境：`http://39.108.65.148:8081`，账号 `inspection`，项目「测试项目」`P-2026-8FC0B5`
（69 节点，10 份真实上传文件，草稿/立项中）。

只找问题，未做修复。

---

## P0

### L-1 · 进入工作台要等 24 秒，单个接口占 20.4 秒

浏览器 Resource Timing（一次登录到工作台可用）：

| 接口 | 耗时 | 大小 |
|---|---:|---:|
| `inspection/audit-overview` | **20 732 ms** | 1.7 MB |
| `workbench/projects` | 781 ms | **6.7 MB** |
| `tree` | 531 ms | 1.5 MB |
| `nodes/24/package` | 508 ms | 34 KB |
| `inspection/submitted-documents` | 416 ms | 2 KB |
| `workbench/context` | 213 ms | 1.1 MB |
| 合计 14 个请求 | **24 088 ms** | — |

服务端复测 20 439 ms，稳定复现，不是冷启动。

**成因**（容器内实测）：`audit-overview` 对项目全部 69 个节点逐个调用
`build_inspection_audit_workspace`，单节点 263 ms → 69 × 263 ms ≈ 18.2 秒。

分页参数在**计算之后**才生效：`summary` 统计的是全部 69 个节点
（`not_started 345 + needs_attention 138 = 483 = 69 × 7`），页面只展示其中一部分。
也就是说为了出一个汇总数字，算了 69 遍再丢掉大半。

### L-2 · 每个响应都内嵌 1.1 MB 的 `businessPackSnapshot`

各接口 `data.project` 字段实测：

| 接口 | 响应总大小 | 其中 `project` |
|---|---:|---:|
| `workbench/projects`（9 个项目） | 6.6 MB | 每项 **1131 KB** |
| `tree` | 1561 KB | 1132 KB |
| `workbench/context` | 1093 KB | 1132 KB |
| `inspection/audit-overview` | 1550 KB | 1132 KB |

一次工作台加载重复传输同一份快照 4 次以上（约 4.5 MB）；项目列表页只需要项目名和
状态，却传了 9 份完整业务包快照。

仓库里已有 `project_without_business_pack_snapshot()`（`routes.py:2404`），
但全库只在 2 处被调用，这四个高频端点都没用。

---

## P1

### L-3 · OCR 标记「证据就绪」，实际抽出的是 `OCR文本1..5`、置信度全 0

项目里 10 份文件，抽到字段的那几份长这样：

```
ocrReadiness.status : "ready"        ← 系统告诉监检「证据就绪」
artifactIntegrity   : true
bbox 覆盖率          : 100%
字段名               : OCR文本, OCR文本2, OCR文本3, OCR文本4, OCR文本5
字段置信度           : 全部 0.0
```

界面上呈现为「OCR 证据就绪 · bbox 100%」，点开却是五条编号文本片段、每条标着
「置信度 0% 低置信度」。

监检要的是「设计压力 = 4.0 MPa」这种业务字段。现在的产物是把正文切成片段编号，
**没有做字段识别**。而就绪度指标只校验了「有文本 + 有坐标 + 产物完整」，没有校验
「抽出了业务字段」——于是一份对审查毫无用处的资料，被系统判为就绪。

这与本轮反复出现的那类问题同源：**指标绿了，事情没成**。

### L-4 · Office 文件标着「可定位」，但根本无法预览

10 份文件全是 `.docx`，`previewType: office`。右侧每个字段都带「可定位」标签，
点击后提示「该条证据位于第 1 页」，左侧始终是：

> Office 文件不支持在线预览 —— Word/Excel 等 Office 文件暂不支持在线预览，
> 请使用右上角「下载」查看原文。

bbox 100% 覆盖的坐标数据完全用不上。这不是提示文案的问题——是**这个项目的全部
资料都无法在系统内核对**，监检只能下载到本地用 Word 打开，再自己对照。

### L-5 · 全新项目 0 份资料，却显示 138 项「需关注」

项目状态「草稿/立项中」、`资料 0`，`audit-overview` 汇总：

```
未开始 345 · 处理中 0 · 需关注 138 · 执行失败 0 · 已完成 0
```

逐节点看，每个节点的 `submission` 与 `evidence` 都是 `needs_attention`：

- 资料提交：「仍有 3 项必传资料未匹配。」
- 证据确认：「仍有必传审查点缺少已确认资料证据，不能形成满足要求类结论。」

对一个刚立项、尚未开始报送的项目，这两条描述的是「还没做」，不是「出了问题」。
把它们计为需关注，等于开局就有 138 个红点——真正需要关注的事项将淹没其中。

### L-6 · AI 复核返回成功，实际执行失败

```
POST inspection/nodes/24/ai-recheck   → 5476 ms, code=0
最新 run                              → status=失败, confidence=0.0
说明                                   → "AI 复核任务已进入队列，完成后将更新审查建议。"
```

接口返回成功、界面显示「已进入队列」，而运行记录已经是「失败」。成因是
LiteLLM 服务未部署（镜像在 ghcr，该网络不可达），但这个失败没有传达给用户——
留下的是一句「完成后将更新」，用户会一直等。

---

## P2

### L-7 · 部分接口返回体没有 `code` 字段

```
/api/projects/{id}/todos                → code=None
/api/knowledge/retrieval-test?query=…   → code=None
```

其余接口统一返回 `{code, message, data}`。这两个不带 `code`，调用方若按统一契约
判断成功与否会取到 `undefined`。

### L-8 · 一份文件 OCR 状态为 `incomplete` 但界面无提示

`DOC-7D4C29BE`（材料代用设计变更.docx）：

```
ocrReadiness.status : "incomplete"
artifactIntegrity   : false
字段 0 | 证据 0
```

文件列表里与其他文件并列展示，没有任何「这份没抽出东西」的标识。

---

## 未覆盖

- 只审了 `inspection` 角色（其余角色口令未提供）；
- 未做移动端/窄屏走查；
- 未做键盘导航与读屏器完整走查；
- 报告与归档链路数据为空（0 条），未能验证。

---

## 附：与前几轮的关系

- 节点切换慢（上一轮修的 `standards` 端点）在本项目**不复现**：该项目条款绑定
  完整，`standards` 仅 32–118 ms。前一轮 5.5 秒的成因是主 demo 项目
  `P-2026-HDCP-001` **一条条款绑定都没有**，掉进知识检索兜底。
- 文件详情弹窗 1325 px、三页签、`aria-pressed` 切换均正常（X-1/X-2/X-6 生效）。
- 定时轮询已消失（线上产物 `setInterval=0`）。
