# 第三轮 · 真实素材本地审计（2026-08-11）

环境：本地 venv 直跑（无 docker），后端 uvicorn:8399 + 前端 vite:5199，鉴权开启，
六个角色（inspection/contractor/ndt/owner/admin/fde）真实登录。
素材：`Scan/` 目录的真实监检资料（焊工证、焊接工艺评定报告、特种设备制造许可证、
射线检测报告、产品质量证明、压力管道强度计算书等），以施工方角色上传 8 份。

**本轮只找问题，未改动任何产品代码。共 11 项有效发现（M-1、M-3..M-12），其中 M-2 经深挖后由我自行撤回。**

---

## M-1 · 资料自动分类把 11/14 份资料归到同一个节点 【P1】

`POST /projects/{pid}/documents/batch-classify` 用真实素材的实测结果：

| 资料 | 应归节点 | 实际建议 | 置信度 |
|---|---|---|---|
| 射线检测报告.pdf | R40 无损检测记录、报告 | **16** | 0.82 |
| 焊接工艺评定报告.pdf | R25 焊接工艺文件 | **16** | 0.82 |
| 特种设备制造许可证-河北广浩.pdf | R12 元件制造单位许可 | **16** | 0.82 |
| 特种设备安装改造维修许可证.pdf | R02 施工单位许可资质 | **16** | 0.82 |
| 压力管道强度计算书.png | R06 强度计算书审批手续 | **16** | 0.82 |
| 产品质量证明part1.pdf | R16 产品质量证明文件 | **16** | 0.82 |
| 工艺图纸目录.png | R04 设计文件批准程序 | **16** | 0.82 |
| 焊工证.pdf | R24 焊工资格证 | 24 ✅ | 0.82 |

**14 份资料中 11 份被归到节点 16**，置信度一律 0.82。

这是 02 报告 R-9（`routes.py:7372` 硬编码 stub：文件名含「焊工」→24，否则一律 16）在真实数据下的后果。
之前只是「代码里是假的」，现在可以量化：**自动分类的准确率约 21%（3/14，且这 3 份都只是碰巧含「焊工」二字）**。
按业务规模（单项目几千页），监检人员实际要手工重挂几乎全部资料。

---

## ~~M-2 · 同一节点的绑定数在两个接口间不一致~~ 【已撤回——我的误判】

**原判断（错误）**：挂载成功后 `documents/bindings?nodeId=24` 返回 4 条，
而 `nodes/24/package` 返回 `bindings: []`，据此认为两接口数据不一致、
监检人员看不到刚挂的资料。

**深挖后的事实**：这是**既定业务规则，不是缺陷**。
[routes.py:6172-6185](../../backend/apps/api/routes.py) 对 `inspection` 角色专门过滤，
`package.bindings` 只保留 `SUBMITTED_DOCUMENT_BINDING_STATUSES`（已提交/需补正/已通过）
中的绑定 —— 即**监检人员只审已提交的资料，不看施工方的草稿**。

佐证：常量 `SUBMITTED_DOCUMENT_BINDING_STATUSES`（routes.py:308）、
提交记录 `a3bd08a fix: enforce submitted document review lifecycle`、
专项测试 `frontend/src/views/AICheck/inspectionSubmittedDocuments.test.ts`。

实测（提交之后再看，数字自洽）：

| 角色 | `package.bindings` | 状态构成 |
|---|---|---|
| inspection | 2 | 已提交 ×2 —— 按规则过滤 |
| contractor | 5 | 含草稿挂载 |
| owner | 5 | 含草稿挂载 |
| ndt | 403 | 不在节点范围 |

我当初观察到 0 条，是因为那一刻绑定还是「草稿挂载」、尚未提交，
监检视角看不到本就正确。**撤回该发现**。

仅存的次要问题：`documents/bindings?nodeId=24` 对监检返回 5 条（含草稿），
`package` 返回 2 条，同一角色两个接口口径不同且无任何说明，
容易让调用方（含我）误判。属文档/契约问题，非数据缺陷。

---

## M-11 · 建设方能看到施工方尚未提交的草稿资料 【P1】

承 M-2 深挖发现：监检人员被规则限定为「只看已提交资料」，
但 **`owner`（建设方）没有这层过滤**：

```
inspection  package.bindings = 2   ['已提交','已提交']
owner       package.bindings = 5   含 2 条「草稿挂载」
            BIND-24-1DEE47  焊工证.pdf     草稿挂载
            BIND-24-002     焊工名册.xlsx  草稿挂载
```

即：**建设方看到的资料比监检人员还多**，包括施工方挂上去但**尚未正式提交**的草稿。

施工方在正式提交前应当有整理、替换、撤回的空间；草稿阶段的资料被出资方直接看到，
既不符合「已提交才进入审查视野」的业务规则，也让施工方失去提交前的自主权。

与 M-9 同源（读端点不按角色裁剪），但危害更具体：M-9 是「看到已发生的审查过程」，
这里是「看到尚未提交的半成品」。

---

## M-12 · 建设方的「总体进度」是硬编码 42% 【P1】

[routes.py:5313](../../backend/apps/api/routes.py)：

```python
if resolved_role == "owner":
    metrics = [
        {"key": "progress", "label": "总体进度", "value": "42%", "tone": "blue"},
        ...
    ]
```

实测跨项目对比：

| 项目 | 报告版本 | 归档资料 | **总体进度** |
|---|---|---|---|
| P-2026-HDCP-001 | 9 | 2 | **42%** |
| P-2026-GDLNG-002 | 0 | 0 | **42%** |

两个项目的实际状态天差地别（一个有 9 份报告 2 条归档，另一个全为 0），
**进度都显示 42%**。

业务口径中建设方的核心用途正是「查看资料和进度」——
而进度这个唯一的核心指标是假的，且是三项指标中唯一被写死的
（报告版本、归档资料都取自真实数据）。

对照：监检人员的指标全部真实（待办 27 / 补正 2 / 资料 28 / 报告 9）。

**建议**：按已通过节点数 ÷ 总节点数计算，数据在 `tree_nodes` 里现成可用。

---

## M-3 · 上传会话响应体回显完整 JWT 【P2】

`POST /projects/{pid}/documents/upload-session` 的响应：

```json
"uploadUrls": [{
  "url": "/api/projects/.../upload-session/UPS-xxx/files/DV-xxx",
  "headers": {
    "Content-Type": "application/pdf",
    "Authorization": "Bearer eyJhbGciOi...",   ← 完整 JWT，343 字符
    "X-Role": "contractor",
    "X-Upload-Session-Token": "..."
  }
}]
```

把调用方自己的 JWT 原样回显在响应体里，对调用方没有增益（它本来就持有该 token），
却扩大了泄漏面：响应体会进入浏览器 devtools、前端日志、错误上报、网关访问日志。
`X-Upload-Session-Token` 是本次上传专用的短时凭证，回显它是合理的；`Authorization` 不是。

**建议**：`headers` 只回 `Content-Type` 和 `X-Upload-Session-Token`，由客户端自行附加登录态。

---

## M-4 · 未上传内容的文档进入资料台账 【P2】

只创建上传会话、不 PUT 任何内容，文档记录即出现在监检人员的资料台账中：

```
台账显示: {'fileName': '从未上传的文件.pdf', 'currentOcrStatus': '排队中',
          'materialTypeCode': 'generic_review_material'}
```

与真实文档在列表中无可视区分。业务红线明确写着
「目录中列出文件不能等同于文件本体已上传」。

**缓解因素**（已实测确认，故定 P2 而非 P1）：
- 原件下载正确拒绝：返回 `OBJECT_STORAGE_REQUIRED`，不会串到其他文档的内容；
- 节点证据就绪度不把它算作已满足（仍为 `缺 3`），不会污染判定结论。

问题只在台账呈现层——监检人员需要能一眼看出哪些是空壳记录。

---

## M-5 · 重复上传无去重、无提示 【P3】

同一文件（`焊工证.pdf`，sha256 一致）上传 5 次产生 5 条独立文档记录，
无重复标记、无提示。几千页规模下，多人协作重复提交同一份资料会显著膨胀台账。

**建议**：按 `hash + projectId` 检测，提示「已存在相同文件」并允许复用既有文档。

---

## M-8 · 上传时声明的 nodeIds 被静默丢弃 【P1】

施工方上传时显式声明资料类型与归属节点：

```json
{"fileName":"焊接工艺评定报告.pdf", "materialTypeCode":"welding_procedure_qualification",
 "nodeIds":[25]}
```

会话响应**正常回显**：`materialTypeCode: welding_procedure_qualification`、`nodeIds: [25]`。
但完成上传后查台账：

| 字段 | 落库值 |
|---|---|
| materialTypeCode | `welding_procedure_qualification` ✅ |
| materialTypeName | **None** |
| materialCategory | **None** |
| nodeId / nodeIds | **None** ❌ |

**声明的节点归属没有落库**，资料仍是游离状态，需要再手工挂载一次。
`materialTypeName` / `materialCategory` 也未按 code 解析填充。

**对照组**：NDT 专用上传路径（`POST /ndt/reports/upload-session`）上传同一批真实素材时，
落库结果完整：

```
materialTypeCode  = ndt_report
materialTypeName  = 无损检测报告
materialCategory  = 无损检测资料
nodeId            = 40          ← 自动绑定到正确节点
sourceOrgName     = 华测检测有限公司
```

即：**系统具备按类型自动定名、归类、挂载的能力，通用上传路径没有接上**。
这也让 M-1 的成因更清楚——不是「做不到分类」，而是通用路径既没有推断、
声明了也不生效。

---

## M-6 · 打回后无法用新上传的资料补正 【P1·流程断点】

跨角色跑「施工方提交 → 监检打回 → 施工方补正」时卡住：

```
POST /projects/{pid}/rectifications
→ 40900 只有监检退回为需补正状态的资料才能重新提交。
```

约束在 [routes.py:7787-7796](../../backend/apps/api/routes.py)：提交的每个 binding 自身
`bindingStatus` 必须等于「需补正」。新上传并挂载的资料状态是「草稿挂载」，
因此**永远无法作为补正材料提交**。

实测对比：
- 用被打回的那条旧 binding 提交 → ✅ 成功，整改单转「已重新提交」
- 上传新版焊工证、挂到同一节点后提交 → ❌ 40900 拒绝

**业务影响**：监检打回的典型理由就是「资料不对/不全，请补充」——施工方本应上传**新**资料。
现在只能就原文件重新提交一次（内容没变），或者绕过整改单走普通提交流程，
导致整改单与实际补正的资料脱钩，整改闭环的可追溯性断掉。

**待确认**：若业务上要求「补正必须针对被打回的原资料」（例如换版必须走文档版本追加
`POST /documents/{id}/versions` 而非新建文档），那这是设计意图，缺的是明确的错误引导；
否则是流程缺陷。错误信息目前没有告诉施工方该怎么做。

---

## M-9 · 建设方（observer）可读全部审查过程数据 【P1·扩大了 issue #18】

`owner` 角色定位为 `observer`，动作表只有
`[project:view, file:view, file:preview, report:view, archive:view, archive:download]`。
实测以 owner 身份读取：

| 端点 | 结果 |
|---|---|
| `/reports` | **9 份**监督检验报告全文 |
| `/archive` | 2 条归档 |
| `/documents` | **20 份**资料台账（含施工方与 NDT 提交的全部原始资料）|
| `/rectifications` | **3 条整改单**，含打回理由「焊工证持证项目未覆盖本工程焊接方法，请补充。」|
| `/inspection/nodes/{n}/review-opinions` | 监检人工结论 |
| `/inspection/nodes/{n}/ai-runs` | **9 条 AI 运行记录**，含建议结论与判定描述全文 |

即：建设方能看到**施工方被打回的全过程、监检人员的人工结论、AI 的逐条判定理由**。

写路径正确拦截（`review:save` / `file:bind` 均 403 FORBIDDEN），
问题只在读路径——与 issue #18（施工方/NDT 可读报告）同源：动作矩阵不作用于 GET。
本轮把影响面从「报告」扩大到「资料台账 + 整改过程 + AI 判定 + 人工结论」，
且涉及第三个角色。

业务上建设方看到多少是可以商量的（毕竟是出资方），但**当前实现是「读端点全开」，
而非「按角色决定」** —— 这与最小权限口径和角色声明都不一致。

---

## M-7 · 补正反馈文本静默丢弃 【P2】

[routes.py:7807](../../backend/apps/api/routes.py) 只接受 `comment` / `description`：

```python
rectification["feedbackComment"] = body.get("comment") or body.get("description")
```

传其他字段名（如 `feedback`、`response`）时，请求返回 **code 0 成功**，
`feedbackAt`、`feedbackByName` 都正常写入，唯独说明文本为 `None` —— 无报错、无警告。

实测：
```
{"feedback": "已补充覆盖本工程焊接方法的焊工证。"}  → code 0，feedbackComment = None
{"comment":  "用 comment 字段提交的说明"}          → code 0，feedbackComment 正常
```

对比同一业务链上的打回接口用的是 `reason`，落库字段叫 `comment`；补正接口入参是 `comment`，
落库字段叫 `feedbackComment`。**同一条整改链上三个不同的字段名**，且未知字段静默丢弃。

**业务影响**：施工方写的整改说明丢失，监检人员复审时看不到对方解释了什么。
写操作应对未识别的必要字段报错，而非静默接受。

---

## M-10 · 写端点字段命名分歧与静默丢弃（全量扫描） 【P2】

沿 M-7 的线索对全部写端点做了系统扫描。

**扫描口径**：解析 `routes.py` 中全部 `@router.post/put/patch`，提取各自实际读取的
`body.get("...")` 键；对「说明文字类」字段按业务域分组，比较命名一致性；
再逐个实测传错名时是否静默成功。

### 命名分歧

读取 body 的写端点共 **121 个**。同一语义的说明字段有 **7 种命名**：

| 字段名 | 端点数 |
|---|---|
| reason | 32 |
| comment | 12 |
| opinion | 4 |
| description | 3 |
| remark | 2 |
| text | 2 |
| content | 1 |

**9 个业务域内部命名不一致**，同一操作对的两端用不同字段名：

| 业务域 | 分歧 |
|---|---|
| ai-suggestions | adopt 用 `opinion` / reject 用 `reason` |
| findings | accept 用 `opinion` / reject 用 `reason` |
| review-runs | human-decision 用 `comment` / cancel、rerun 用 `reason` |
| ndt | submissions 用 `comment` / rectifications 用 `description` |
| releases | approve 用 `comment` / submit、rollback 用 `reason` |
| ocr-annotation tasks | label、review 用 `comment` / cancel 用 `reason` |
| nodes | review-opinions 用 `opinion` / fact-corrections 用 `reason` |

### 有无校验：一半一半

对说明字段做了必填/非空校验的 **24 个**，无校验的 **25 个**。
后者传错名即静默丢弃，请求仍返回成功。

**实测验证**（避免仅凭静态分析下结论）：

| 端点 | 传入 | 结果 |
|---|---|---|
| `ai-suggestions/{id}/reject` | `opinion`（应 `reason`）| ✅ 40001 拒绝 |
| `review-runs/{id}/cancel` | `comment`（应 `reason`）| ✅ 40001 拒绝 |
| `actions/return-correction` | `comment`（应 `reason`）| ✅ 40001 拒绝 |
| `fact-corrections` | `note`（应 `reason`）| ❌ **code 0，reason 落库 None** |
| `rectifications` | `feedback`（应 `comment`）| ❌ **code 0，说明丢失**（即 M-7）|

即：**业务主链上的关键写操作大多有校验并正确拒绝**；静默丢弃集中在
可选说明字段上，其中 `fact-corrections` 是我本轮之前新增的接口，同样有此问题。

### 非说明类字段

也测了会影响判定的参数，结论是**服务端派生优先，属正确设计**：

| 传入 | 落库 | 判定 |
|---|---|---|
| `riskLevel: 高` | `高` | 接受（合理）|
| `basis: TSG D7006 D2.6.1` | 同值 | 接受（合理）|
| `closeStatus: 已关闭` | `未关闭` | **忽略——正确**，关闭状态不应由创建方自定 |
| `severity: critical` | `None` | 忽略（该端点无此字段）|
| `advisoryOnly: False` | `True` | **忽略——正确**，由 `reviewMode` 派生（routes.py:8287），防止调用方自行提级 |
| `modelAlias` / `priority` | `None` | 忽略——服务端决定 |

### 建议

1. 统一说明字段命名（建议全用 `comment`，或至少同一业务域内一致）；
2. 写端点对未识别的 body 键返回警告或拒绝，而非静默接受——
   当前调用方无法区分「字段名写错」与「服务端不需要该字段」；
3. 若短期不改契约，至少在响应中回显实际采纳的字段，让调用方可自检。

---

## 本轮确认正确的部分

| 项 | 实测 |
|---|---|
| 上传链路完整性校验 | 会话令牌（`X-Upload-Session-Token`）、文件大小、内容哈希三重校验，缺一即拒 |
| 完成清单一致性 | `completedFiles` 与会话文件不符时拒绝（「上传完成清单与上传会话文件不一致」） |
| 哈希不符拒绝 | 声明哈希与实际存储不符时拒绝（「上传文件哈希与完成清单不一致」） |
| 未上传内容的原件下载 | 正确拒绝，**不存在串读其他文档内容的问题**（已用不同文件对照验证：射线检测报告与焊工证返回各自内容，哈希不同） |
| 证据就绪门禁 | 空壳文档不计入满足项，正式复核仍被拦住 |
| 已提交资料生命周期 | 监检 `package.bindings` 按 `SUBMITTED_DOCUMENT_BINDING_STATUSES` 过滤，只审已提交资料，不看施工方草稿（规则明确、有常量有测试）|
| 关键写操作的必填校验 | 打回单、AI 建议驳回、ReviewRun 取消传错字段名时均正确返回 40001，不静默接受 |
| 服务端派生优先 | `advisoryOnly` 由 reviewMode 派生、`closeStatus` 不由创建方自定，调用方无法自行提级或改写关键状态 |
| 六角色登录 | 全部成功，JWT 正常签发 |
| 本地无 docker 部署 | venv + uvicorn + vite 直跑，无需容器 |
| 施工方提交流程 | 挂载 → 提交 → 节点转「待审查」，绑定状态转「已提交」，全链路正常 |
| 监检打回流程 | 生成整改单、写入打回理由（`comment` 字段完整）、节点转「需补正」、施工方可见 |
| 补正闭环（原资料） | 用被打回的 binding 提交 → 整改单转「已重新提交」，记录 `resubmissionId`、`feedbackByName`（李工）、`feedbackAt` |
| 跨角色可见性 | 施工方能看到发给自己的整改单及打回理由 |
| NDT 专用上传链路 | 会话 → PUT → complete 全通，落库自动定名、归类、绑定节点 40、记录检测机构名 |
| NDT 工作台数据面 | films / records / reports / summary 四个端点均正常，报告进 NDT 台账（状态「待提交」）|

---

## 一处我自己的误判（已更正）

审计过程中我一度认为「上传失败的空壳文档能下载到其他文档的内容」，
依据是两个 `焊工证.pdf` 文档返回了相同字节数。核对后确认：
二者本就是同一个文件（sha256 一致），返回相同内容是正确的；
射线检测报告返回的是不同内容（2837594 字节，哈希不同）。
决定性测试（从未上传内容的文档）显示系统正确拒绝下载。
**不存在证据完整性问题。**

---

## 环境备注

- OCR 状态与导出任务均停在「排队中」，因本地未起 Celery worker，非缺陷；
  导出产物接口相应返回「该导出任务未使用本地文件产物」，行为一致；
  若要跑通 OCR→抽取→判定全链路，需另起 worker 或接远端 OCR 服务。
- 本地访问：前端 http://127.0.0.1:5199 ，后端 http://127.0.0.1:8399
