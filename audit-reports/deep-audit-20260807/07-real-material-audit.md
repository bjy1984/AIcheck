# 第三轮 · 真实素材本地审计（2026-08-11）

环境：本地 venv 直跑（无 docker），后端 uvicorn:8399 + 前端 vite:5199，鉴权开启，
六个角色（inspection/contractor/ndt/owner/admin/fde）真实登录。
素材：`Scan/` 目录的真实监检资料（焊工证、焊接工艺评定报告、特种设备制造许可证、
射线检测报告、产品质量证明、压力管道强度计算书等），以施工方角色上传 8 份。

**本轮只找问题，未改动任何产品代码。共 9 项发现（M-1..M-9）。**

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

## M-2 · 同一节点的绑定数在两个接口间不一致（0 vs 4） 【P1】

绑定成功后：

```
POST /projects/{pid}/documents/bindings   → code 0，objectId BIND-24-619B2F
GET  /projects/{pid}/documents/bindings?nodeId=24  → 4 条（含新建的 BIND-24-619B2F）
GET  /projects/{pid}/nodes/24/package     → bindings: []          ← 空
```

同一节点、同一时刻，两个接口给出 4 条和 0 条。`package` 是监检工作台的主数据源，
监检人员在界面上看不到刚挂载的资料，会以为挂载失败而重复操作
（本次审计中我正是因此重复挂载了两次，产生 `BIND-24-619B2F` 和 `BIND-24-ABE662` 两条重复绑定）。

节点证据就绪度也始终停在 `缺 3`，不随绑定变化。

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

## 本轮确认正确的部分

| 项 | 实测 |
|---|---|
| 上传链路完整性校验 | 会话令牌（`X-Upload-Session-Token`）、文件大小、内容哈希三重校验，缺一即拒 |
| 完成清单一致性 | `completedFiles` 与会话文件不符时拒绝（「上传完成清单与上传会话文件不一致」） |
| 哈希不符拒绝 | 声明哈希与实际存储不符时拒绝（「上传文件哈希与完成清单不一致」） |
| 未上传内容的原件下载 | 正确拒绝，**不存在串读其他文档内容的问题**（已用不同文件对照验证：射线检测报告与焊工证返回各自内容，哈希不同） |
| 证据就绪门禁 | 空壳文档不计入满足项，正式复核仍被拦住 |
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

- OCR 状态停在「排队中」是因为本地未起 Celery worker，非缺陷；
  若要跑通 OCR→抽取→判定全链路，需另起 worker 或接远端 OCR 服务。
- 本地访问：前端 http://127.0.0.1:5199 ，后端 http://127.0.0.1:8399
