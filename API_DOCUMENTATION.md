# AIcheck API 文档

本文档根据 `系统设计.docx`、`uidesign.md`、`AI_KNOWLEDGE_BASE_DESIGN.md`、`ui/UI_DESIGN_INTERACTION_MAP.md`、`ui/static_ui_nav.js`、`ui/workbench_api.js` 和现有静态页面整理。目标是让 `vue-element-plus-admin` 前端在不改业务口径的前提下完成接口对接。

## 1. 覆盖目标

本 API 合同覆盖以下前端入口和业务域：

- 四类工作台：监检、施工方、无损检测、建设方。
- 管理后台：项目、组织用户、权限、流程、节点模板、规则模板、工具源、字段映射、审计。
- AI 知识库管理：知识源、项目文件知识库、OCR/切片/向量任务、规则版本、检索测试、推理日志、多 LLM 对比、配置、审计。
- 通用能力：项目切换、全局搜索、待办、消息、文件预览、下载、导出、证据定位、刷新、筛选、只读说明。
- 追溯能力：文件版本、节点挂载、提交快照、OCR 字段、EvidenceLink、AI run、审查意见、报告版本、归档包、审计日志。

## 2. 通用约定

### 2.1 响应包装

```ts
type ApiResult<T> =
  | {
      code: 0;
      data: T;
      message?: string;
      operationId: string;
      serverTime: string;
    }
  | {
      code: number;
      message: string;
      data?: {
        reason: BusinessErrorReason;
        [key: string]: unknown;
      };
      operationId: string;
      serverTime: string;
    };

type BusinessErrorReason =
  | "VALIDATION_ERROR"
  | "AUTH_REQUIRED"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "CONFLICT"
  | "FILE_TOO_LARGE"
  | "UNSUPPORTED_FILE_TYPE"
  | "TASK_RUNNING"
  | "ARCHIVED_READONLY"
  | "ETAG_CONFLICT"
  | "IDEMPOTENCY_KEY_CONFLICT"
  | "EXTERNAL_TOOL_FAILED"
  | "AI_RUN_FAILED"
  | string;

type Page<T> = {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
};

type ListQuery = {
  page?: number;
  pageSize?: number;
  keyword?: string;
  sortBy?: string;
  sortOrder?: "asc" | "desc";
  filters?: Record<string, string | number | boolean | string[]>;
};
```

### 2.2 标准查询参数

所有列表接口支持：

| 参数        | 类型       | 说明                     |
| ----------- | ---------- | ------------------------ |
| `page`      | number     | 页码，从 1 开始          |
| `pageSize`  | number     | 每页条数，默认 20        |
| `keyword`   | string     | 全文关键词               |
| `sortBy`    | string     | 排序字段                 |
| `sortOrder` | `asc/desc` | 排序方向                 |
| `projectId` | string     | 项目过滤，跨项目页面可选 |
| `nodeId`    | number     | 检测节点过滤             |
| `status`    | string     | 状态过滤                 |
| `role`      | string     | 当前角色视图             |

### 2.3 错误码

| reason                  | 说明                         |
| ----------------------- | ---------------------------- |
| `VALIDATION_ERROR`      | 请求字段校验失败             |
| `AUTH_REQUIRED`         | 未登录                       |
| `FORBIDDEN`             | 无角色、项目、节点或动作权限 |
| `NOT_FOUND`             | 对象不存在或无权访问         |
| `CONFLICT`              | 状态冲突、版本冲突或重复提交 |
| `FILE_TOO_LARGE`        | 文件超出限制                 |
| `UNSUPPORTED_FILE_TYPE` | 文件类型不支持               |
| `TASK_RUNNING`          | 任务正在运行，不能重复触发   |
| `ARCHIVED_READONLY`     | 项目或报告已归档，只读       |
| `ETAG_CONFLICT`         | 数据版本已变化，需刷新后重试 |
| `IDEMPOTENCY_KEY_CONFLICT` | 幂等键已被不同请求内容使用 |
| `EMPTY_BINDINGS`        | 资料挂载未选择有效资料       |
| `EMPTY_NODE_PACKAGE`    | 当前节点没有可提交资料       |
| `WITHDRAW_LOCKED`       | 已通过或锁定资料不能撤回     |
| `EXTERNAL_TOOL_FAILED`  | 外部核验工具失败             |
| `AI_RUN_FAILED`         | AI 审查任务失败              |

### 2.4 角色枚举

```ts
type RoleCode = "inspection" | "contractor" | "ndt" | "owner" | "admin";
```

### 2.5 动作权限枚举

页面上下文、树节点、表格行和详情接口都可以返回 `actions: ActionCode[]`。前端用它控制显隐，后端仍必须校验。

```ts
type ActionCode =
  | "project:view"
  | "project:create"
  | "project:update"
  | "project:initialize-workflow"
  | "project:authorize-member"
  | "tree:view"
  | "tree:configure"
  | "file:view"
  | "file:upload"
  | "file:bind"
  | "file:replace-version"
  | "file:append-version"
  | "file:withdraw"
  | "file:void"
  | "file:download"
  | "file:preview"
  | "submission:draft"
  | "submission:submit"
  | "rectification:submit"
  | "review:save"
  | "review:return-correction"
  | "ai:recheck"
  | "ai:adopt"
  | "ai:reject"
  | "prompt:version-manage"
  | "report:generate"
  | "report:review"
  | "report:update"
  | "report:export"
  | "report:archive"
  | "archive:view"
  | "archive:download"
  | "ndt:film-create"
  | "ndt:record-import"
  | "ndt:report-upload"
  | "ndt:submit"
  | "knowledge:view"
  | "knowledge:manage"
  | "knowledge:task-retry"
  | "knowledge:reindex"
  | "rule:manage"
  | "rule:publish"
  | "rule:rollback"
  | "admin:config"
  | "admin:export"
  | "audit:view";
```

## 3. 状态枚举

```ts
type ProjectStatus =
  | "草稿/立项中"
  | "资料提交中"
  | "AI 预审中"
  | "监检审查中"
  | "退回补正中"
  | "报告生成/复核中"
  | "已归档";

type NodeStatus =
  | "待提交"
  | "部分提交"
  | "已提交"
  | "识别中"
  | "业务核验中"
  | "待审查"
  | "待人工确认"
  | "需补正"
  | "补正中"
  | "复审中"
  | "已通过"
  | "报告生成/复核中"
  | "已归档";

type FileStatus =
  | "草稿"
  | "已上传"
  | "已撤回"
  | "已替换"
  | "已追加版本"
  | "已作废"
  | "软删除";

type BindingStatus =
  | "未挂载"
  | "草稿挂载"
  | "已提交"
  | "需补正"
  | "已通过"
  | "已解除挂载"
  | "历史挂载";

type OcrStatus =
  | "未识别"
  | "排队中"
  | "识别中"
  | "已识别"
  | "识别失败"
  | "人工修正";
type SliceStatus = "未切片" | "切片中" | "已切片" | "切片失败";
type VectorStatus =
  | "未向量化"
  | "向量化中"
  | "已向量化"
  | "向量化失败"
  | "索引过期";
type RuleStatus = "草稿" | "待发布" | "已发布" | "已停用" | "已回滚";
type ReasoningStatus = "待推理" | "推理中" | "完成" | "失败" | "已人工确认";
type KnowledgeStatus = "启用" | "停用" | "过期" | "待复核";
```

## 4. 核心类型

### 4.1 项目和组织

```ts
type Project = {
  id: string;
  code: string;
  name: string;
  type: string;
  region: string;
  address?: string;
  ownerOrgName: string;
  contractorOrgName?: string;
  ndtOrgName?: string;
  inspectionOrgName?: string;
  pipelineLevel?: string;
  plannedStartDate?: string;
  plannedEndDate?: string;
  status: ProjectStatus;
  updatedAt: string;
  actions: ActionCode[];
};

type ProjectUnit = {
  id: string;
  projectId: string;
  unitType: "建设方" | "施工方" | "无损检测机构" | "设计单位" | "监检机构";
  unitName: string;
  licenseNo?: string;
  contactName?: string;
  contactPhone?: string;
};

type User = {
  id: string;
  username: string;
  displayName: string;
  orgUnitId: string;
  orgUnitName: string;
  defaultRole: RoleCode;
  accountStatus: "启用" | "停用" | "待激活";
};
```

### 4.2 项目树和节点

```ts
type ProjectTreeNode = {
  id: string;
  projectId: string;
  nodeId?: number;
  parentId?: string;
  code: string;
  name: string;
  type: "project" | "group" | "inspectionNode";
  category?: string;
  inspectionType?: "A" | "B" | "C" | "C/B" | "需确认";
  sortOrder: number;
  enabled: boolean;
  status?: NodeStatus;
  fileCount?: number;
  requiredProgress?: { done: number; total: number };
  badges?: Array<{
    text: string;
    tone: "blue" | "green" | "orange" | "red" | "gray";
  }>;
  actions: ActionCode[];
};

type NodeDocumentRequirement = {
  id: string;
  nodeId: number;
  name: string;
  requiredType: "必传" | "条件必传" | "可选";
  roleScope: RoleCode[];
  templateRequirement?: string;
  note?: string;
};
```

### 4.3 文件、挂载和证据

```ts
type DocumentAsset = {
  id: string;
  projectId: string;
  fileName: string;
  fileType: string;
  sourceOrgId: string;
  sourceOrgName: string;
  uploaderId: string;
  uploaderName: string;
  currentVersionId: string;
  fileStatus: FileStatus;
  currentOcrStatus: OcrStatus;
  createdAt: string;
  updatedAt: string;
  actions: ActionCode[];
};

type DocumentVersion = {
  id: string;
  documentId: string;
  versionNo: string;
  hash: string;
  fileSize: number;
  storageKey: string;
  ocrStatus: OcrStatus;
  parseStatus?: string;
  sliceStatus?: SliceStatus;
  vectorStatus?: VectorStatus;
  uploadTime: string;
  uploaderName: string;
  isCurrent: boolean;
};

type NodeFileBinding = {
  id: string;
  projectId: string;
  nodeId: number;
  requirementId?: string;
  requirementName?: string;
  documentId: string;
  documentVersionId: string;
  fileName: string;
  versionNo: string;
  usage:
    | "原始提交"
    | "补正附件"
    | "整改说明"
    | "证明材料"
    | "监检资料"
    | "检测报告"
    | "检测记录";
  sourceOrgName: string;
  bindingStatus: BindingStatus;
  reviewStatus?: NodeStatus;
  rectificationRound?: number;
  boundByName: string;
  boundAt: string;
  actions: ActionCode[];
};

type EvidenceLink = {
  id: string;
  objectType:
    | "documentVersion"
    | "extractedField"
    | "knowledgeClause"
    | "aiRun"
    | "reviewOpinion"
    | "externalToolResult";
  objectId: string;
  documentId?: string;
  documentVersionId?: string;
  fileName?: string;
  pageNo?: number;
  region?: { x: number; y: number; width: number; height: number };
  fieldName?: string;
  quotedText?: string;
  screenshotUrl?: string;
  clauseId?: string;
  confidence?: number;
};
```

### 4.4 OCR、AI 和审查

```ts
type ExtractedField = {
  id: string;
  documentVersionId: string;
  fieldName: string;
  fieldValue: string;
  pageNo?: number;
  region?: EvidenceLink["region"];
  confidence: number;
  extractionMethod: string;
  reviewStatus: "未复核" | "已确认" | "已修正" | "低置信度";
  evidenceLinkId: string;
};

type AiReviewRun = {
  id: string;
  projectId: string;
  nodeId: number;
  subject: string;
  model: string;
  promptVersion: string;
  ruleVersion: string;
  toolVersion?: string;
  inputDocumentVersionIds: string[];
  status: ReasoningStatus;
  startedAt: string;
  finishedAt?: string;
  steps: AiReviewStep[];
  suggestion: AiSuggestion;
  evidenceLinks: EvidenceLink[];
  humanResult?: "采纳" | "修改后采纳" | "驳回" | "重新分析";
};

type AiReviewStep = {
  id: string;
  title: string;
  inputSummary: string;
  action: string;
  conclusion: "通过" | "需补正" | "待人工确认" | "不适用";
  evidenceLinkIds: string[];
};

type AiSuggestion = {
  id: string;
  result: "满足要求" | "需补正" | "不适用" | "需人工确认";
  opinionDraft: string;
  risks: string[];
  rectificationSuggestion?: string;
  confidence: number;
  manualConfirmItems: string[];
};

type ReviewOpinion = {
  id: string;
  projectId: string;
  nodeId: number;
  result: "满足要求" | "需补正" | "不适用";
  opinion: string;
  basis?: string;
  riskLevel?: "低" | "中" | "高";
  responsibleOrgId?: string;
  closeStatus: "未关闭" | "已关闭";
  evidenceLinkIds: string[];
  reviewerName: string;
  createdAt: string;
};
```

### 4.5 报告、归档和审计

```ts
type ReportVersion = {
  id: string;
  projectId: string;
  templateVersion: string;
  reportNo?: string;
  title: string;
  status: "草稿" | "复核中" | "已确认" | "已导出" | "已归档";
  generatedAt: string;
  generatedByName: string;
  dataSnapshotId: string;
  exportFiles?: Array<{
    format: "docx" | "pdf";
    fileId: string;
    downloadUrl?: string;
  }>;
  actions: ActionCode[];
};

type AuditLog = {
  id: string;
  actorId: string;
  actorName: string;
  actorOrgName: string;
  action: string;
  objectType: string;
  objectId: string;
  beforeValue?: unknown;
  afterValue?: unknown;
  result: "成功" | "失败";
  ip?: string;
  device?: string;
  createdAt: string;
};
```

## 5. 权限、菜单和用户 API

| 方法   | 路径                                                                              | 说明                                  |
| ------ | --------------------------------------------------------------------------------- | ------------------------------------- |
| `GET`  | `/api/auth/me`                                                                    | 当前用户、单位、默认角色、项目授权    |
| `GET`  | `/api/auth/routes?role={role}`                                                    | `vue-element-plus-admin` 动态路由菜单 |
| `GET`  | `/api/auth/actions?projectId={projectId}&role={role}`                             | 页面级动作权限                        |
| `GET`  | `/api/permissions/node-actions?projectId={projectId}&nodeId={nodeId}&role={role}` | 节点动作权限                          |
| `GET`  | `/api/permissions/resources?role={role}`                                          | 接口资源权限配置展示                  |
| `POST` | `/api/auth/logout`                                                                | 退出登录                              |

## 6. 项目与工作台 API

| 方法        | 路径                                                      | 说明                                |
| ----------- | --------------------------------------------------------- | ----------------------------------- |
| `GET`       | `/api/workbench/projects?role={role}`                     | 授权项目列表，支撑项目切换          |
| `GET`       | `/api/projects`                                           | 项目列表/台账                       |
| `POST`      | `/api/projects`                                           | 项目立项                            |
| `GET`       | `/api/projects/{projectId}`                               | 项目详情                            |
| `PATCH`     | `/api/projects/{projectId}`                               | 更新项目基础信息                    |
| `GET`       | `/api/projects/{projectId}/participants`                  | 参建单位列表                        |
| `POST`      | `/api/projects/{projectId}/participants`                  | 绑定参建单位                        |
| `PATCH`     | `/api/projects/{projectId}/participants/{participantId}`  | 更新参建单位                        |
| `GET`       | `/api/projects/{projectId}/members`                       | 项目成员                            |
| `POST`      | `/api/projects/{projectId}/members`                       | 项目成员授权                        |
| `PUT/PATCH` | `/api/projects/{projectId}/members/{memberId}`            | 更新成员角色/节点范围               |
| `POST`      | `/api/projects/{projectId}/initialize-workflow`           | 套用 69 节点模板并初始化流程        |
| `GET`       | `/api/projects/{projectId}/workbench/context?role={role}` | 顶部栏、当前用户、项目状态、actions |
| `GET`       | `/api/projects/{projectId}/workbench/summary?role={role}` | 指标、待办、消息、异常汇总          |
| `GET`       | `/api/projects/{projectId}/tree?role={role}`              | 统一项目树                          |
| `GET`       | `/api/projects/{projectId}/nodes/{nodeId}`                | 检测节点详情                        |
| `GET`       | `/api/projects/{projectId}/nodes/{nodeId}/package`        | 当前节点文件包和项目文件包          |
| `GET`       | `/api/projects/{projectId}/nodes/{nodeId}/requirements`   | 节点资料项要求                      |

## 7. 文件中心 API

| 方法     | 路径                                                                      | 说明                       |
| -------- | ------------------------------------------------------------------------- | -------------------------- |
| `GET`    | `/api/projects/{projectId}/documents`                                     | 项目文件库列表             |
| `GET`    | `/api/projects/{projectId}/documents/{documentId}`                        | 文件详情                   |
| `GET`    | `/api/projects/{projectId}/documents/{documentId}/versions`               | 历史版本                   |
| `POST`   | `/api/projects/{projectId}/documents/upload-session`                      | 创建上传会话               |
| `POST`   | `/api/projects/{projectId}/documents/upload-session/{sessionId}/complete` | 上传完成，生成文件版本     |
| `POST`   | `/api/projects/{projectId}/documents/{documentId}/versions`               | 替换或追加版本             |
| `POST`   | `/api/projects/{projectId}/documents/bindings`                            | 保存节点挂载关系           |
| `GET`    | `/api/projects/{projectId}/documents/bindings`                            | 挂载关系列表               |
| `PATCH`  | `/api/projects/{projectId}/documents/bindings/{bindingId}`                | 更新资料项/用途/备注       |
| `DELETE` | `/api/projects/{projectId}/documents/bindings/{bindingId}`                | 解除草稿挂载               |
| `POST`   | `/api/projects/{projectId}/documents/{documentId}/withdraw`               | 撤回未提交文件             |
| `POST`   | `/api/projects/{projectId}/documents/{documentId}/void`                   | 作废文件                   |
| `POST`   | `/api/projects/{projectId}/documents/batch-classify`                      | 批量归类，返回建议节点     |
| `GET`    | `/api/projects/{projectId}/documents/{documentId}/preview-url`            | 文件预览地址               |
| `GET`    | `/api/projects/{projectId}/documents/{documentId}/download-url`           | 文件下载地址               |
| `GET`    | `/api/projects/{projectId}/documents/{documentId}/ocr-fields`             | OCR 字段、置信度和证据区域 |
| `GET`    | `/api/projects/{projectId}/documents/{documentId}/review-feedback`        | 文件关联反馈/意见          |

## 8. 提交、补正和流程 API

| 方法    | 路径                                                                  | 说明                 |
| ------- | --------------------------------------------------------------------- | -------------------- |
| `POST`  | `/api/projects/{projectId}/submissions/drafts`                        | 保存草稿             |
| `GET`   | `/api/projects/{projectId}/submissions/drafts/{draftId}`              | 草稿详情             |
| `GET`   | `/api/projects/{projectId}/submissions`                               | 提交历史和草稿列表   |
| `POST`  | `/api/projects/{projectId}/submissions`                               | 提交文件及挂载关系   |
| `GET`   | `/api/projects/{projectId}/submissions/{submissionId}`                | 提交快照详情         |
| `POST`  | `/api/projects/{projectId}/submissions/{submissionId}/withdraw-items` | 撤回未提交项         |
| `POST`  | `/api/projects/{projectId}/rectifications`                            | 提交补正反馈         |
| `GET`   | `/api/projects/{projectId}/rectifications`                            | 补正任务/反馈列表    |
| `GET`   | `/api/projects/{projectId}/rectifications/{rectificationId}`          | 补正详情             |
| `GET`   | `/api/projects/{projectId}/workflow`                                  | 当前项目流程状态     |
| `GET`   | `/api/projects/{projectId}/workflow/instances/{workflowId}`           | 流程实例详情         |
| `GET`   | `/api/projects/{projectId}/workflow/timeline`                         | 项目或节点流转时间线 |
| `GET`   | `/api/admin/workflow-state-machines`                                  | 状态机配置           |
| `POST`  | `/api/admin/workflow-state-machines`                                  | 新增状态机版本       |
| `PATCH` | `/api/admin/workflow-state-machines/{stateMachineId}`                 | 更新状态机版本       |

## 9. 搜索、待办和消息 API

| 方法    | 路径                                                  | 说明                                             |
| ------- | ----------------------------------------------------- | ------------------------------------------------ |
| `GET`   | `/api/search?projectId={projectId}&keyword={keyword}` | 全局搜索，返回文件、节点、底片、报告、标准、规则 |
| `GET`   | `/api/todos?role={role}&projectId={projectId}`        | 待办列表                                         |
| `GET`   | `/api/todos/{todoId}`                                 | 待办详情                                         |
| `POST`  | `/api/todos/{todoId}/complete`                        | 完成待办                                         |
| `POST`  | `/api/todos/{todoId}/defer`                           | 延期/稍后处理                                    |
| `GET`   | `/api/messages?projectId={projectId}`                 | 消息列表                                         |
| `POST`  | `/api/messages/{messageId}/read`                      | 标记已读                                         |
| `POST`  | `/api/messages/read-all`                              | 全部已读                                         |
| `GET`   | `/api/admin/todo-rules`                               | 待办规则配置                                     |
| `POST`  | `/api/admin/todo-rules`                               | 新增待办规则                                     |
| `PATCH` | `/api/admin/todo-rules/{ruleId}`                      | 更新待办规则                                     |
| `GET`   | `/api/admin/message-templates`                        | 消息模板                                         |
| `POST`  | `/api/admin/message-templates`                        | 新增消息模板                                     |
| `PATCH` | `/api/admin/message-templates/{templateId}`           | 更新消息模板                                     |

## 10. 监检审查 API

| 方法   | 路径                                                                                       | 说明                       |
| ------ | ------------------------------------------------------------------------------------------ | -------------------------- |
| `POST` | `/api/projects/{projectId}/inspection/nodes/{nodeId}/attachments`                          | 上传监检资料并挂载当前节点 |
| `POST` | `/api/projects/{projectId}/inspection/nodes/{nodeId}/file-bindings`                        | 监检从项目文件包挂载文件   |
| `POST` | `/api/projects/{projectId}/inspection/nodes/{nodeId}/ai-recheck`                           | 重新核验                   |
| `GET`  | `/api/projects/{projectId}/inspection/nodes/{nodeId}/ai-runs`                              | AI 审查运行历史            |
| `GET`  | `/api/projects/{projectId}/inspection/nodes/{nodeId}/ai-runs/{runId}`                      | AI 审查链路详情            |
| `POST` | `/api/projects/{projectId}/inspection/nodes/{nodeId}/review-opinions`                      | 保存审查意见               |
| `GET`  | `/api/projects/{projectId}/inspection/nodes/{nodeId}/review-opinions`                      | 审查意见历史               |
| `POST` | `/api/projects/{projectId}/inspection/nodes/{nodeId}/ai-suggestions/{suggestionId}/adopt`  | 采纳 AI 建议为草稿         |
| `POST` | `/api/projects/{projectId}/inspection/nodes/{nodeId}/ai-suggestions/{suggestionId}/reject` | 驳回 AI 建议               |
| `POST` | `/api/projects/{projectId}/inspection/nodes/{nodeId}/actions/return-correction`            | 退回补正                   |
| `GET`  | `/api/projects/{projectId}/inspection/nodes/{nodeId}/evidence-chain`                       | 证据链                     |
| `GET`  | `/api/projects/{projectId}/inspection/nodes/{nodeId}/standards`                            | 标准依据                   |
| `GET`  | `/api/projects/{projectId}/inspection/nodes/{nodeId}/date-compare`                         | 日期覆盖比对               |
| `GET`  | `/api/projects/{projectId}/inspection/nodes/{nodeId}/rules/current-version`                | 当前规则版本               |
| `GET`  | `/api/projects/{projectId}/inspection/nodes/{nodeId}/review-log`                           | 审查记录 Tab               |

## 11. 无损检测 API

| 方法    | 路径                                                   | 说明                |
| ------- | ------------------------------------------------------ | ------------------- |
| `GET`   | `/api/projects/{projectId}/ndt/summary`                | 无损检测工作台摘要  |
| `GET`   | `/api/projects/{projectId}/ndt/films`                  | 底片编号列表        |
| `POST`  | `/api/projects/{projectId}/ndt/films`                  | 新增底片编号        |
| `GET`   | `/api/projects/{projectId}/ndt/films/{filmId}`         | 底片详情            |
| `PATCH` | `/api/projects/{projectId}/ndt/films/{filmId}`         | 更新底片            |
| `POST`  | `/api/projects/{projectId}/ndt/films/import`           | 批量导入底片        |
| `GET`   | `/api/projects/{projectId}/ndt/records`                | 检测记录列表        |
| `POST`  | `/api/projects/{projectId}/ndt/records/import`         | 批量导入检测记录    |
| `GET`   | `/api/projects/{projectId}/ndt/reports`                | 检测报告列表        |
| `GET`   | `/api/projects/{projectId}/ndt/reports/{reportId}`     | 检测报告详情        |
| `POST`  | `/api/projects/{projectId}/ndt/reports/upload-session` | 上传检测报告/图像包 |
| `POST`  | `/api/projects/{projectId}/ndt/submissions`            | 提交检测资料        |
| `POST`  | `/api/projects/{projectId}/ndt/rectifications`         | 无损检测补正反馈    |
| `GET`   | `/api/projects/{projectId}/ndt/inspection-feedback`    | 查看监检意见        |

## 12. 建设方、报告和归档 API

| 方法    | 路径                                                                | 说明                   |
| ------- | ------------------------------------------------------------------- | ---------------------- |
| `GET`   | `/api/projects/{projectId}/owner/dashboard`                         | 建设方项目概况         |
| `GET`   | `/api/projects/{projectId}/owner/node-summary`                      | 节点资料摘要           |
| `GET`   | `/api/projects/{projectId}/owner/reports`                           | 报告预览列表           |
| `GET`   | `/api/projects/{projectId}/reports`                                 | 报告版本列表           |
| `POST`  | `/api/projects/{projectId}/inspection/nodes/{nodeId}/report-review` | 生成报告草稿并进入复核 |
| `GET`   | `/api/projects/{projectId}/reports/{reportId}`                      | 报告详情               |
| `PATCH` | `/api/projects/{projectId}/reports/{reportId}`                      | 保存报告编辑内容       |
| `GET`   | `/api/projects/{projectId}/reports/{reportId}/versions`             | 报告版本历史           |
| `POST`  | `/api/projects/{projectId}/reports/{reportId}/export`               | 导出 Word/PDF          |
| `POST`  | `/api/projects/{projectId}/reports/{reportId}/archive`              | 报告归档               |
| `GET`   | `/api/projects/{projectId}/archive`                                 | 归档资料浏览           |
| `GET`   | `/api/projects/{projectId}/archive/package`                         | 归档包下载地址         |
| `GET`   | `/api/projects/{projectId}/archive/evidence-package`                | 证据定位包下载地址     |

## 13. 导出和下载 API

| 方法   | 路径                                   | 说明                                                       |
| ------ | -------------------------------------- | ---------------------------------------------------------- |
| `POST` | `/api/exports`                         | 创建导出任务，覆盖状态摘要、节点清单、检测资料清单、配置包 |
| `GET`  | `/api/exports/{exportId}`              | 导出任务状态                                               |
| `GET`  | `/api/exports/{exportId}/download-url` | 导出文件下载地址                                           |
| `GET`  | `/api/downloads/{fileId}/signed-url`   | 受控下载地址                                               |

## 14. AI 知识库 API

| 方法        | 路径                                                 | 说明                  |
| ----------- | ---------------------------------------------------- | --------------------- |
| `GET`       | `/api/knowledge/overview`                            | 知识库总览            |
| `GET`       | `/api/knowledge/sources`                             | 知识源列表            |
| `POST`      | `/api/knowledge/sources`                             | 新增知识源            |
| `GET`       | `/api/knowledge/sources/{sourceId}`                  | 知识源详情            |
| `PUT/PATCH` | `/api/knowledge/sources/{sourceId}`                  | 更新知识源            |
| `POST`      | `/api/knowledge/sources/{sourceId}/enable`           | 启用知识源            |
| `POST`      | `/api/knowledge/sources/{sourceId}/disable`          | 停用知识源            |
| `GET`       | `/api/knowledge/project-files`                       | 项目文件知识库列表    |
| `GET`       | `/api/knowledge/files/{fileId}`                      | 文件知识详情          |
| `GET`       | `/api/knowledge/files/{fileId}/chunks`               | 文件切片              |
| `GET`       | `/api/knowledge/files/{fileId}/vectors`              | 向量索引摘要          |
| `GET`       | `/api/knowledge/files/{fileId}/reasoning-references` | 推理引用历史          |
| `GET`       | `/api/knowledge/tasks`                               | OCR/切片/向量任务列表 |
| `GET`       | `/api/knowledge/tasks/{taskId}`                      | 任务详情              |
| `GET`       | `/api/knowledge/tasks/{taskId}/logs`                 | 任务日志              |
| `POST`      | `/api/knowledge/tasks/{taskId}/retry`                | 重试任务              |
| `POST`      | `/api/knowledge/tasks/{taskId}/cancel`               | 取消排队任务          |
| `POST`      | `/api/knowledge/files/{fileId}/reindex`              | 重建单文件索引        |
| `POST`      | `/api/knowledge/reindex`                             | 批量重建索引          |
| `GET`       | `/api/knowledge/config`                              | 知识库配置            |
| `PUT/PATCH` | `/api/knowledge/config`                              | 保存知识库配置        |
| `POST`      | `/api/knowledge/retrieval-test`                      | 知识检索测试          |
| `GET`       | `/api/rules/versions`                                | 规则版本列表          |
| `GET`       | `/api/rules/versions/{versionId}/diff`               | 规则版本差异          |
| `POST`      | `/api/rules/versions/{versionId}/publish`            | 发布规则版本          |
| `POST`      | `/api/rules/versions/{versionId}/rollback`           | 回滚规则版本          |
| `GET`       | `/api/reasoning/logs`                                | 推理链路历史          |
| `GET`       | `/api/reasoning/logs/{logId}`                        | 推理链路详情          |
| `GET`       | `/api/reasoning/logs/{logId}/evidence`               | 推理证据              |
| `POST`      | `/api/llm/compare`                                   | 发起多模型对比        |
| `GET`       | `/api/llm/compare-runs`                              | 多模型对比记录        |
| `GET`       | `/api/llm/compare-runs/{runId}`                      | 多模型对比详情        |

## 15. 规则、Prompt、工具源和字段映射 API

| 方法    | 路径                                                                         | 说明                   |
| ------- | ---------------------------------------------------------------------------- | ---------------------- |
| `GET`   | `/api/admin/rules/templates`                                                 | 规则模板列表           |
| `POST`  | `/api/admin/rules/templates`                                                 | 新增规则模板           |
| `GET`   | `/api/admin/rules/templates/{templateId}`                                    | 规则模板详情           |
| `PATCH` | `/api/admin/rules/templates/{templateId}`                                    | 编辑规则模板           |
| `POST`  | `/api/admin/rules/templates/{templateId}/copy`                               | 复制规则模板           |
| `GET`   | `/api/admin/rules/templates/{templateId}/diff?from={versionA}&to={versionB}` | 版本差异               |
| `GET`   | `/api/rules/versions`                                                        | 规则版本列表           |
| `GET`   | `/api/rules/versions/{versionId}/diff`                                       | 规则版本差异           |
| `POST`  | `/api/rules/versions/{versionId}/publish`                                    | 发布规则版本           |
| `POST`  | `/api/rules/versions/{versionId}/rollback`                                   | 回滚规则版本           |
| `GET`   | `/api/projects/{projectId}/nodes/{nodeId}/prompts`                           | 节点 Prompt 版本列表   |
| `POST`  | `/api/projects/{projectId}/nodes/{nodeId}/prompts`                           | 保存节点 Prompt 新版本 |
| `POST`  | `/api/projects/{projectId}/nodes/{nodeId}/prompts/{promptId}/rollback`       | 回滚节点 Prompt        |
| `POST`  | `/api/projects/{projectId}/nodes/{nodeId}/prompts/{promptId}/test`           | Prompt 样本测试        |
| `GET`   | `/api/admin/tool-sources`                                                    | 外部核验工具源列表     |
| `POST`  | `/api/admin/tool-sources`                                                    | 新增工具源             |
| `PATCH` | `/api/admin/tool-sources/{toolSourceId}`                                     | 更新工具源             |
| `GET`   | `/api/admin/field-mappings`                                                  | 证据字段映射列表       |
| `POST`  | `/api/admin/field-mappings`                                                  | 新增字段映射           |
| `PATCH` | `/api/admin/field-mappings/{mappingId}`                                      | 更新字段映射           |

## 16. 后台配置 API

| 方法    | 路径                                         | 说明                         |
| ------- | -------------------------------------------- | ---------------------------- |
| `GET`   | `/api/admin/tree-nodes`                      | 节点模板列表                 |
| `POST`  | `/api/admin/tree-nodes`                      | 新增节点模板                 |
| `PATCH` | `/api/admin/tree-nodes/{treeNodeId}`         | 更新节点模板                 |
| `POST`  | `/api/admin/tree-nodes/{treeNodeId}/enable`  | 启用节点                     |
| `POST`  | `/api/admin/tree-nodes/{treeNodeId}/disable` | 停用节点                     |
| `GET`   | `/api/admin/node-role-mappings`              | 节点角色权限矩阵             |
| `POST`  | `/api/admin/node-role-mappings`              | 保存权限矩阵                 |
| `GET`   | `/api/admin/org-units`                       | 单位列表                     |
| `POST`  | `/api/admin/org-units`                       | 新增单位                     |
| `PATCH` | `/api/admin/org-units/{orgUnitId}`           | 更新单位                     |
| `GET`   | `/api/admin/users`                           | 用户列表                     |
| `POST`  | `/api/admin/users`                           | 新增用户                     |
| `PATCH` | `/api/admin/users/{userId}`                  | 更新用户                     |
| `POST`  | `/api/admin/users/{userId}/status`           | 启停用户                     |
| `GET`   | `/api/admin/roles`                           | 角色列表                     |
| `POST`  | `/api/admin/roles`                           | 新增角色                     |
| `PATCH` | `/api/admin/roles/{roleId}`                  | 更新角色                     |
| `GET`   | `/api/admin/integration-contract`            | 真实联调字段差异清单         |
| `POST`  | `/api/admin/config-export`                   | 导出规则、权限、字段映射配置 |
| `GET`   | `/api/admin/audit-logs`                      | 审计日志                     |

## 17. 审计 API

| 方法  | 路径                                                  | 说明           |
| ----- | ----------------------------------------------------- | -------------- |
| `GET` | `/api/audit-logs`                                     | 全局审计日志   |
| `GET` | `/api/projects/{projectId}/audit-logs`                | 项目审计日志   |
| `GET` | `/api/projects/{projectId}/nodes/{nodeId}/audit-logs` | 节点审计日志   |
| `GET` | `/api/knowledge/audit-logs`                           | 知识库审计日志 |

### 17.1 兼容别名和静态原型旧接口映射

以下接口来自 `ui/static_ui_interactions.html` 的“接口预留”或权限表。后端建议只实现右侧规范路径；若前端仍沿用旧路径，网关或 mock 层应按本表做兼容转发。

| 静态原型路径                                  | 规范 API                                                                             | 处理口径                                                                                                                                                                          |
| --------------------------------------------- | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /api/projects/{id}`                      | `GET /api/projects/{projectId}`                                                      | `{id}` 等价 `{projectId}`                                                                                                                                                         |
| `GET /api/projects/{id}/participants`         | `GET /api/projects/{projectId}/participants`                                         | `{id}` 等价 `{projectId}`                                                                                                                                                         |
| `GET /api/projects/{id}/workflow`             | `GET /api/projects/{projectId}/workflow`                                             | `{id}` 等价 `{projectId}`                                                                                                                                                         |
| `POST /api/projects/{id}/participants`        | `POST /api/projects/{projectId}/participants`                                        | `{id}` 等价 `{projectId}`                                                                                                                                                         |
| `POST /api/projects/{id}/initialize-workflow` | `POST /api/projects/{projectId}/initialize-workflow`                                 | `{id}` 等价 `{projectId}`                                                                                                                                                         |
| `GET /api/orgs`                               | `GET /api/admin/org-units`                                                           | 组织单位列表旧别名                                                                                                                                                                |
| `GET /api/users`                              | `GET /api/admin/users`                                                               | 用户列表旧别名                                                                                                                                                                    |
| `POST /api/users/{id}/status`                 | `POST /api/admin/users/{userId}/status`                                              | `{id}` 等价 `{userId}`                                                                                                                                                            |
| `POST /api/files/upload`                      | `POST /api/projects/{projectId}/documents/upload-session`                            | 施工方资料上传入口；监检上传走 `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/attachments`，无损检测报告走 `POST /api/projects/{projectId}/ndt/reports/upload-session` |
| `POST /api/reviews/{id}/return`               | `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/actions/return-correction` | `{id}` 等价审查意见或节点上下文，返回体必须包含补正任务 ID                                                                                                                        |
| `POST /api/admin/rules`                       | `POST /api/admin/rules/templates`                                                    | 规则模板新增旧别名                                                                                                                                                                |
| `PUT /api/admin/rules`                        | `PATCH /api/admin/rules/templates/{templateId}`                                      | 规则模板编辑旧别名；请求体必须携带 `templateId`                                                                                                                                   |
| `POST /api/todos/rules`                       | `POST /api/admin/todo-rules`                                                         | 待办规则新增旧别名                                                                                                                                                                |
| `POST /api/messages/templates`                | `POST /api/admin/message-templates`                                                  | 消息模板新增旧别名                                                                                                                                                                |

## 18. 关键请求示例

### 18.1 创建上传会话

```json
POST /api/projects/P-2026-HDCP-001/documents/upload-session
{
  "files": [
    { "fileName": "炉批号差异说明.pdf", "fileSize": 245760, "fileType": "application/pdf" }
  ],
  "sourceOrgId": "ORG-CONTRACTOR-001",
  "defaultUsage": "补正附件",
  "defaultNodeIds": [16, 18],
  "remark": "材料补正资料"
}
```

### 18.2 保存挂载关系

```json
POST /api/projects/P-2026-HDCP-001/documents/bindings
{
  "bindings": [
    {
      "documentVersionId": "DV-001",
      "nodeId": 16,
      "requirementId": "REQ-16-01",
      "usage": "补正附件",
      "remark": "炉批号差异说明"
    }
  ]
}
```

### 18.3 保存审查意见

```json
POST /api/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions
{
  "result": "满足要求",
  "opinion": "焊工资格证书真实有效，持证项目和项目焊接作业要求匹配。",
  "evidenceLinkIds": ["EV-001", "EV-002"],
  "aiRunId": "AIRUN-24-20260625-01"
}
```

### 18.4 退回补正

```json
POST /api/projects/P-2026-HDCP-001/inspection/nodes/24/actions/return-correction
{
  "responsibleOrgId": "ORG-CONTRACTOR-001",
  "deadline": "2026-06-28 18:00:00",
  "requirement": "请补充最新资格网站查询截图。",
  "evidenceLinkIds": ["EV-003"],
  "bindingIds": ["BIND-001"]
}
```

### 18.5 知识检索测试

```json
POST /api/knowledge/retrieval-test
{
  "question": "焊工资格证有效期是否覆盖项目施工周期？",
  "scope": ["standard", "project-file", "rule"],
  "projectId": "P-2026-HDCP-001",
  "nodeId": 24,
  "topK": 10
}
```

## 19. 页面入口覆盖矩阵

| 静态入口                   | API 覆盖                                                                                                                                 |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `global-search`            | `GET /api/search`                                                                                                                        |
| `todo-center`              | `GET /api/todos`、`POST /api/todos/{todoId}/complete`                                                                                    |
| `message-center`           | `GET /api/messages`、`POST /api/messages/{messageId}/read`                                                                               |
| `user-menu`                | `GET /api/auth/me`、`GET /api/auth/routes`、`GET /api/auth/actions`                                                                      |
| `project-list`             | `GET /api/projects`、`GET /api/workbench/projects`                                                                                       |
| `project-detail`           | `GET /api/projects/{projectId}`、`GET /api/projects/{projectId}/participants`、`GET /api/projects/{projectId}/workflow`                  |
| `project-create-wizard`    | `POST /api/projects`、`POST /api/projects/{projectId}/participants`、`POST /api/projects/{projectId}/initialize-workflow`                |
| `org-users`                | `GET /api/admin/org-units`、`GET /api/admin/users`                                                                                       |
| `role-permission`          | `GET /api/permissions/resources`、`GET /api/auth/actions`                                                                                |
| `project-member-auth`      | `GET/POST/PATCH /api/projects/{projectId}/members`                                                                                       |
| `workflow-state-machine`   | `GET/POST/PATCH /api/admin/workflow-state-machines`                                                                                      |
| `todo-rule-config`         | `GET/POST/PATCH /api/admin/todo-rules`、`GET/POST/PATCH /api/admin/message-templates`                                                    |
| `workflow-instance-detail` | `GET /api/projects/{projectId}/workflow/instances/{workflowId}`、`GET /api/projects/{projectId}/workflow/timeline`                       |
| `node-detail`              | `GET /api/projects/{projectId}/nodes/{nodeId}`、`GET /api/projects/{projectId}/nodes/{nodeId}/package`                                   |
| `file-detail`              | `GET /api/projects/{projectId}/documents/{documentId}`                                                                                   |
| `file-history`             | `GET /api/projects/{projectId}/documents/{documentId}/versions`                                                                          |
| `feedback-detail`          | `GET /api/projects/{projectId}/documents/{documentId}/review-feedback`、`GET /api/projects/{projectId}/rectifications/{rectificationId}` |
| `contractor-upload`        | `POST /api/projects/{projectId}/documents/upload-session`                                                                                |
| `contractor-mount-node`    | `POST /api/projects/{projectId}/documents/bindings`                                                                                      |
| `contractor-submit`        | `POST /api/projects/{projectId}/submissions`                                                                                             |
| `draft-save`               | `POST /api/projects/{projectId}/submissions/drafts`                                                                                      |
| `withdraw-submit`          | `POST /api/projects/{projectId}/submissions/{submissionId}/withdraw-items`                                                               |
| `feedback-correction`      | `POST /api/projects/{projectId}/rectifications`                                                                                          |
| `ai-recheck`               | `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-recheck`                                                                    |
| `rule-version`             | `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/rules/current-version`                                                          |
| `copy-conclusion`          | 前端剪贴板动作，无后端接口；如需审计可写 `POST /api/audit-logs`                                                                          |
| `inspection-mount-file`    | `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/file-bindings`                                                                 |
| `inspection-upload`        | `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/attachments`                                                                   |
| `inspection-opinion`       | `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/review-opinions`                                                               |
| `ai-adopt`                 | `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-suggestions/{suggestionId}/adopt`                                           |
| `ai-reject`                | `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-suggestions/{suggestionId}/reject`                                          |
| `return-correction`        | `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/actions/return-correction`                                                     |
| `report-review`            | `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/report-review`                                                                 |
| `evidence-locator`         | `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/evidence-chain`                                                                 |
| `evidence-chain`           | `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/evidence-chain`                                                                 |
| `standard-reference`       | `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/standards`                                                                      |
| `date-compare`             | `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/date-compare`                                                                   |
| `preview-zoom`             | 前端视图动作；文件内容来自 `preview-url`                                                                                                 |
| `download-center`          | `GET /api/projects/{projectId}/documents/{documentId}/download-url`、`POST /api/exports`                                                 |
| `ndt-node-detail`          | `GET /api/projects/{projectId}/nodes/{nodeId}`、`GET /api/projects/{projectId}/ndt/summary`                                              |
| `ndt-film-add`             | `POST /api/projects/{projectId}/ndt/films`                                                                                               |
| `ndt-import`               | `POST /api/projects/{projectId}/ndt/films/import`、`POST /api/projects/{projectId}/ndt/records/import`                                   |
| `ndt-upload-report`        | `POST /api/projects/{projectId}/ndt/reports/upload-session`                                                                              |
| `ndt-submit`               | `POST /api/projects/{projectId}/ndt/submissions`                                                                                         |
| `inspection-feedback`      | `GET /api/projects/{projectId}/ndt/inspection-feedback`                                                                                  |
| `owner-node-summary`       | `GET /api/projects/{projectId}/owner/node-summary`                                                                                       |
| `owner-report-preview`     | `GET /api/projects/{projectId}/owner/reports`                                                                                            |
| `archive-browser`          | `GET /api/projects/{projectId}/archive`                                                                                                  |
| `readonly-scope`           | `GET /api/auth/actions`、页面静态说明                                                                                                    |
| `admin-node-tree`          | `GET/POST/PATCH /api/admin/tree-nodes`                                                                                                   |
| `admin-permission-matrix`  | `GET/POST /api/admin/node-role-mappings`                                                                                                 |
| `admin-rule-template`      | `GET/POST/PATCH /api/admin/rules/templates`                                                                                              |
| `admin-tool-source`        | `GET/POST/PATCH /api/admin/tool-sources`                                                                                                 |
| `admin-field-mapping`      | `GET/POST/PATCH /api/admin/field-mappings`                                                                                               |
| `admin-people-role`        | `GET/POST/PATCH /api/admin/users`、`GET/POST/PATCH /api/admin/roles`、`GET/POST/PATCH /api/admin/org-units`                              |
| `admin-version`            | `GET /api/rules/versions`、`GET /api/admin/rules/templates/{templateId}/diff`                                                            |
| `admin-integration`        | `GET /api/admin/integration-contract`                                                                                                    |
| `admin-export`             | `POST /api/admin/config-export`                                                                                                          |
| `export-center`            | `POST /api/exports`、`GET /api/exports/{exportId}`                                                                                       |
| `batch-classify`           | `POST /api/projects/{projectId}/documents/batch-classify`                                                                                |
| `audit-log`                | `GET /api/audit-logs`、`GET /api/projects/{projectId}/audit-logs`                                                                        |
| `filter-settings`          | 前端本地设置；筛选参数进入各列表接口                                                                                                     |
| `refresh-state`            | `GET /api/projects/{projectId}/workbench/summary`                                                                                        |
| `tab-node-files`           | `GET /api/projects/{projectId}/nodes/{nodeId}/package`                                                                                   |
| `tab-preview`              | `GET /api/projects/{projectId}/documents/{documentId}/preview-url`                                                                       |
| `tab-ocr`                  | `GET /api/projects/{projectId}/documents/{documentId}/ocr-fields`                                                                        |
| `tab-ai-review`            | `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-runs/{runId}`                                                                |
| `tab-review-log`           | `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/review-log`                                                                     |
| `kb-overview`              | `GET /api/knowledge/overview`                                                                                                            |
| `standard-library`         | `GET/POST/PUT(PATCH) /api/knowledge/sources`、`POST /api/knowledge/sources/{sourceId}/enable\|disable`                                   |
| `project-file-library`     | `GET /api/knowledge/project-files`                                                                                                       |
| `file-knowledge-detail`    | `GET /api/knowledge/files/{fileId}`、`GET /api/knowledge/files/{fileId}/chunks`                                                          |
| `task-center`              | `GET /api/knowledge/tasks`、`POST /api/knowledge/tasks/{taskId}/retry`                                                                   |
| `retrieval-test`           | `POST /api/knowledge/retrieval-test`                                                                                                     |
| `reasoning-log`            | `GET /api/reasoning/logs`、`GET /api/reasoning/logs/{logId}`                                                                             |
| `llm-compare`              | `POST /api/llm/compare`、`GET /api/llm/compare-runs`                                                                                     |
| `rule-version`             | `GET /api/rules/versions`、`POST /api/rules/versions/{versionId}/publish\|rollback`                                                      |
| `kb-config`                | `GET/PUT(PATCH) /api/knowledge/config`                                                                                                   |
| `kb-audit`                 | `GET /api/knowledge/audit-logs`                                                                                                          |
| `static-action-fallback`   | 不应进入生产；新增按钮必须补路由和 API 映射                                                                                              |

## 20. 前端联调最小闭环

1. 项目切换：`GET /api/workbench/projects` -> `GET /api/projects/{projectId}/workbench/context` -> `GET /api/projects/{projectId}/tree`。
2. 施工方提交：上传会话 -> 保存挂载 -> 保存草稿 -> 提交批次 -> 生成待办和消息。
3. 监检审查：节点文件包 -> AI run -> 证据链 -> 保存意见/退回补正 -> 报告草稿。
4. 补正闭环：补正任务 -> 上传补正附件 -> 提交补正 -> 监检复审。
5. 无损检测：底片/记录导入 -> 报告上传 -> 节点挂载 -> 提交检测资料。
6. 建设方只读：项目概况 -> 节点摘要 -> 报告预览 -> 归档浏览。
7. 知识库：总览 -> 任务中心 -> 失败重试 -> 文件详情 -> 推理日志 -> 多模型对比。
8. 后台配置：节点模板 -> 权限矩阵 -> 规则模板 -> 工具源 -> 字段映射 -> 配置导出 -> 审计日志。
9. 联调准备：真实字段差异清单 -> 按模块/状态筛选 -> 标记阻塞字段 -> 输出后端对账清单。

## 21. 路径和入口 100% 覆盖审计结论

已覆盖：

- `ui/static_ui_interactions.html` 中 68 个静态 section 和 114 个静态锚点跳转。
- `ui/static_ui_nav.js` 中映射的全部业务入口。
- `ui/workbench_api.js` 中现有 mock/live 预留接口。
- `AI_KNOWLEDGE_BASE_DESIGN.md` 中 11 个 AI 知识库页面。
- `uidesign.md` 中四类工作台、管理后台、Prompt 版本、权限显隐、状态标签和关键交互流程。
- `系统设计.docx` 核心数据模型中的项目、权限、资料、检验、知识、AI 审查、报告归档、审计实体。

前端不需要后端接口的入口：

- `copy-conclusion`：浏览器剪贴板动作。
- `preview-zoom`：纯前端缩放。
- `filter-settings`：本地列设置和筛选配置；具体筛选作用于列表接口。
- `readonly-scope`：只读范围说明；权限数据来自 `GET /api/auth/actions`。
- `static-action-fallback`：静态原型兜底页，生产环境不应出现。

后续若新增页面或按钮，必须同步更新本文档第 19 节覆盖矩阵，并为非纯前端动作补充 API。

## 22. 前端 Mock 开发参数和输出契约

### 22.1 深度审计结论

本节按“能否直接支撑 `vue-element-plus-admin` 前端 mock 开发”重新审计。结论如下：

| 审计项               | 结论           | 处理                                                                                          |
| -------------------- | -------------- | --------------------------------------------------------------------------------------------- |
| 页面入口和接口路径   | 充足           | 第 19 节已经覆盖全部页面入口、锚点、旧接口别名                                                |
| 核心业务对象         | 基本充足       | 第 4 节已有项目、节点、文件、挂载、证据、AI、报告、审计实体                                   |
| 请求参数             | 原文档不够     | 本节补齐 query、path、body 的 mock 开发口径                                                   |
| 输出字段             | 原文档不够     | 本节补齐每类接口必须返回的 `data` 结构                                                        |
| 状态流转             | 原文档偏弱     | 本节要求所有 mutation 返回 `nextStatus`、`changed`、`todoDelta`、`messageDelta`               |
| 错误态 mock          | 原文档偏弱     | 本节补齐前端必须模拟的 8 类错误和触发条件                                                     |
| 前端 mock 开发       | 补齐后可支撑   | 可据本节编写 MSW、Mock.js、Vite mock 或本地 `workbench_api.js` 适配层                         |
| 后端 OpenAPI/codegen | 已补充过渡合同 | 第 23 节补齐字段校验、header、幂等、并发、状态机和 OpenAPI 拆分建议；生成 SDK 前仍需落成 YAML |

### 22.2 Mock 基础规则

所有 mock 响应必须仍使用第 2 节 `ApiResult<T>` 包装。前端 mock 层允许额外返回 `mock: true`、`endpoint`、`received` 用于调试，但正式联调数据必须放在 `data` 内。

```ts
type MockMutationResult = {
  id: string;
  objectType: string;
  objectId: string;
  nextStatus?: string;
  changed: Array<{ field: string; before?: unknown; after: unknown }>;
  todoDelta?: number;
  messageDelta?: number;
  auditLogId: string;
  affectedIds?: string[];
};

type SignedUrl = {
  url: string;
  expiresAt: string;
  method: "GET" | "PUT" | "POST";
  headers?: Record<string, string>;
};

type SelectOption = {
  label: string;
  value: string | number;
  disabled?: boolean;
  meta?: Record<string, unknown>;
};
```

Mock 数据种子建议固定：

| 字段                | 默认值                                            |
| ------------------- | ------------------------------------------------- |
| `projectId`         | `P-2026-HDCP-001`                                 |
| `nodeId`            | `24` 用于监检，`16` 用于施工方，`40` 用于无损检测 |
| `documentId`        | `DOC-20260625-001`                                |
| `documentVersionId` | `DV-20260625-001-V2`                              |
| `submissionId`      | `SUB-20260625-238`                                |
| `aiRunId`           | `AIRUN-24-20260625-01`                            |
| `suggestionId`      | `AIS-24-20260625-01`                              |
| `reportId`          | `RPT-20260625-001`                                |

### 22.3 前端必须补充的展示类型

```ts
type CurrentUserPayload = {
  user: User;
  roles: RoleCode[];
  defaultRole: RoleCode;
  currentOrg: { id: string; name: string; type: string };
  authorizedProjectIds: string[];
};

type RoutePayload = {
  routes: Array<{
    path: string;
    name: string;
    component: string;
    meta: {
      title: string;
      icon?: string;
      roles: RoleCode[];
      keepAlive?: boolean;
    };
    children?: RoutePayload["routes"];
  }>;
};

type ActionPermissionPayload = {
  role: RoleCode;
  projectId?: string;
  nodeId?: number;
  actions: ActionCode[];
  readonly: boolean;
  readonlyReason?: string;
};

type ProjectMember = {
  id: string;
  projectId: string;
  userId: string;
  name: string;
  orgName: string;
  role: RoleCode;
  nodeScope: number[];
  actions: ActionCode[];
  status: "启用" | "停用" | "已过期";
  expiresAt?: string;
  updatedAt: string;
};

type ProjectMemberSavePayload = {
  userId: string;
  role: RoleCode;
  nodeScope: number[];
  actions: ActionCode[];
  expiresAt?: string;
};

type AdminProjectDetailPayload = {
  project: Project;
  members: ProjectMember[];
  participantUnits: Array<{
    unitType: "owner" | "contractor" | "ndt" | "inspection";
    unitName: string;
    contactName: string;
    contactPhone: string;
  }>;
  nodeSummary: Array<{
    groupName: string;
    total: number;
    passed: number;
    pending: number;
    correction: number;
  }>;
  recentExportTasks: ExportTask[];
};

type AdminProjectCreatePayload = {
  code?: string;
  name: string;
  type: string;
  region: string;
  ownerOrgName: string;
  contractorOrgName: string;
  ndtOrgName: string;
  inspectionOrgName: string;
  currentNodeId?: number;
  memberUserIds?: Partial<Record<RoleCode, string>>;
};

type AdminProjectCreateResult = {
  project: Project;
  detail: AdminProjectDetailPayload;
  auditLogId: string;
  createdNodeCount: number;
};

type AdminConfigTarget =
  | "permission"
  | "node-template"
  | "workflow"
  | "todo-rule"
  | "message-template"
  | "tool-source"
  | "field-mapping";

type AdminRuleVersionSummary = {
  id: string;
  name: string;
  ruleKey: string;
  version: string;
  status: "草稿" | "待发布" | "已发布" | "已回滚";
  nodeIds: number[];
  promptVersion: string;
  outputSchemaVersion: string;
  description?: string;
  publishedAt?: string;
  updatedAt: string;
  actions: ActionCode[];
};

type AdminConfigOverviewPayload = {
  metrics: Array<{
    key: string;
    label: string;
    value: string | number;
    tone: "blue" | "green" | "orange" | "red" | "gray";
  }>;
  orgUnits: Array<{
    id: string;
    name: string;
    type: "owner" | "contractor" | "ndt" | "inspection" | "supervision";
    contactName: string;
    contactPhone: string;
    status: "启用" | "停用" | "待授权";
    projectCount: number;
  }>;
  users: Array<{
    id: string;
    name: string;
    orgName: string;
    role: RoleCode;
    mobile: string;
    status: "启用" | "停用";
    lastLoginAt: string;
  }>;
  permissionMatrix: Array<{
    role: RoleCode;
    label: string;
    projectScope: string;
    nodeScope: string;
    actions: ActionCode[];
    readonly: boolean;
  }>;
  nodeTemplates: Array<{
    id: string;
    version: string;
    groupName: string;
    nodeCount: number;
    requiredCount: number;
    status: "草稿" | "已发布" | "已停用";
    updatedAt: string;
  }>;
  ruleVersions: AdminRuleVersionSummary[];
  workflowStateMachines: Array<{
    id: string;
    name: string;
    version: string;
    states: number;
    transitions: number;
    status: "启用" | "停用";
    updatedAt: string;
  }>;
  todoRules: AdminTodoRule[];
  messageTemplates: AdminMessageTemplate[];
  toolSources: AdminToolSource[];
  fieldMappings: AdminFieldMapping[];
};

type AdminConfigChangePayload =
  | {
      target: "permission";
      id: RoleCode;
      values: {
        label?: string;
        projectScope?: string;
        nodeScope?: string;
        actions?: ActionCode[];
        readonly?: boolean;
      };
      reason: string;
    }
  | {
      target: "node-template";
      id: string;
      values: {
        version?: string;
        groupName?: string;
        nodeCount?: number;
        requiredCount?: number;
        status?: "草稿" | "已发布" | "已停用";
      };
      reason: string;
    }
  | {
      target: "workflow";
      id: string;
      values: {
        name?: string;
        version?: string;
        states?: number;
        transitions?: number;
        status?: "启用" | "停用";
      };
      reason: string;
    };

type AdminConfigDiffPayload = {
  target: AdminConfigTarget;
  objectId: string;
  objectName: string;
  previewedAt: string;
  changed: Array<{
    field: string;
    label: string;
    before?: unknown;
    after?: unknown;
    severity: "info" | "warning";
  }>;
};

type AdminConfigSaveResult = {
  overview: AdminConfigOverviewPayload;
  diff: AdminConfigDiffPayload;
  auditLogId: string;
  updatedAt: string;
};

type WorkbenchContextPayload = {
  currentUser: CurrentUserPayload["user"];
  project: Project;
  role: RoleCode;
  currentNodeId?: number;
  topbar: {
    todoCount: number;
    messageCount: number;
    statusText: string;
    projectSwitcherEnabled: boolean;
  };
  actions: ActionCode[];
};

type WorkbenchSummaryPayload = {
  metrics: Array<{
    key: string;
    label: string;
    value: string | number;
    tone?: "blue" | "green" | "orange" | "red" | "gray";
    trend?: string;
  }>;
  todos: TodoItem[];
  messages: MessageItem[];
  exceptions: Array<{
    id: string;
    level: "info" | "warning" | "danger";
    title: string;
    targetType: string;
    targetId: string;
  }>;
  updatedAt: string;
};

type NodeDetailPayload = {
  node: ProjectTreeNode;
  requirements: NodeDocumentRequirement[];
  packageSummary: {
    requiredTotal: number;
    submittedTotal: number;
    passedTotal: number;
    correctionTotal: number;
  };
  latestAiRun?: AiReviewRun;
  latestOpinion?: ReviewOpinion;
};

type NodePackagePayload = {
  node: ProjectTreeNode;
  requirements: NodeDocumentRequirement[];
  bindings: NodeFileBinding[];
  projectFiles: DocumentAsset[];
  availableVersions: DocumentVersion[];
  extractedFields: ExtractedField[];
  reviewOpinions: ReviewOpinion[];
  aiRuns: AiReviewRun[];
  actions: ActionCode[];
};

type TodoItem = {
  id: string;
  title: string;
  projectId: string;
  nodeId?: number;
  targetType:
    | "node"
    | "document"
    | "submission"
    | "rectification"
    | "report"
    | "knowledgeTask";
  targetId: string;
  status: "待处理" | "处理中" | "已完成" | "已延期" | "已关闭";
  priority: "低" | "中" | "高";
  deadline?: string;
  assigneeName?: string;
  actions: ActionCode[];
};

type MessageItem = {
  id: string;
  title: string;
  content: string;
  projectId?: string;
  targetType?: TodoItem["targetType"];
  targetId?: string;
  read: boolean;
  createdAt: string;
};

type RectificationPayload = {
  id: string;
  projectId: string;
  nodeId: number;
  responsibleOrgId: string;
  responsibleOrgName: string;
  requirement: string;
  deadline: string;
  status: "待补正" | "已反馈" | "复审中" | "已关闭";
  round: number;
  evidenceLinks: EvidenceLink[];
  submittedBindings?: NodeFileBinding[];
};
```

### 22.4 核心工作台接口参数和输出

| 接口                                                        | Query/Path                                                         | Body                                                                       | `data` 输出                                                                                   | Mock 状态变化                              |
| ----------------------------------------------------------- | ------------------------------------------------------------------ | -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------ |
| `GET /api/workbench/projects`                               | `role` 必填；`keyword/status/page/pageSize` 可选                   | 无                                                                         | `Page<Project>`，每项必须含 `todoCount/messageCount/currentNodeId/actions`                    | 无                                         |
| `POST /api/admin/projects`                                  | 无                                                                 | `AdminProjectCreatePayload`                                                | `AdminProjectCreateResult`                                                                    | 新建项目、69 个节点、初始成员授权，写审计  |
| `GET /api/projects/{projectId}`                             | `projectId` 必填                                                   | 无                                                                         | `AdminProjectDetailPayload`                                                                   | 无                                         |
| `GET /api/projects/{projectId}/members`                     | `projectId` 必填；`role/page/pageSize` 可选                        | 无                                                                         | `Page<ProjectMember>`                                                                         | 无                                         |
| `POST /api/projects/{projectId}/members`                    | `projectId` 必填                                                   | `ProjectMemberSavePayload`                                                 | `{ member: ProjectMember; auditLogId: string }`                                               | 新增或覆盖成员授权，写审计                 |
| `PUT/PATCH /api/projects/{projectId}/members/{memberId}`    | `projectId`、`memberId` 必填                                       | `Partial<ProjectMemberSavePayload> & { status?: ProjectMember["status"] }` | `{ member: ProjectMember; auditLogId: string }`                                               | 更新成员角色、节点范围、动作或状态，写审计 |
| `GET /api/projects/{projectId}/workbench/context`           | `projectId`、`role` 必填                                           | 无                                                                         | `WorkbenchContextPayload`                                                                     | 无                                         |
| `GET /api/projects/{projectId}/workbench/summary`           | `projectId`、`role` 必填；`nodeId` 可选                            | 无                                                                         | `WorkbenchSummaryPayload`                                                                     | 无                                         |
| `GET /api/projects/{projectId}/tree`                        | `projectId`、`role` 必填；`includeDisabled` 可选                   | 无                                                                         | `{ project: Project; groups: Array<{ id: string; name: string; nodes: ProjectTreeNode[] }> }` | 无                                         |
| `GET /api/projects/{projectId}/nodes/{nodeId}`              | `projectId`、`nodeId` 必填                                         | 无                                                                         | `NodeDetailPayload`                                                                           | 无                                         |
| `GET /api/projects/{projectId}/nodes/{nodeId}/package`      | `projectId`、`nodeId` 必填；`versionScope=current/latest/all` 可选 | 无                                                                         | `NodePackagePayload`                                                                          | 无                                         |
| `GET /api/projects/{projectId}/nodes/{nodeId}/requirements` | `projectId`、`nodeId` 必填                                         | 无                                                                         | `NodeDocumentRequirement[]`                                                                   | 无                                         |

`NodePackagePayload` 是前端 mock 的关键聚合接口，必须一次返回节点页首、资料项、当前挂载、可挂载项目文件、OCR 字段、AI run 和审查记录。否则前端会被迫拆太多 mock 请求，状态很难保持一致。

### 22.5 文件、上传、挂载接口参数和输出

| 接口                                                                           | Query/Path                                                                        | Body                                                                                                                                                                                    | `data` 输出                                                                                                                                          | Mock 状态变化                                                                                       |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | -------------------- |
| `GET /api/projects/{projectId}/documents`                                      | `projectId` 必填；`nodeId/status/sourceOrgId/fileType/keyword/page/pageSize` 可选 | 无                                                                                                                                                                                      | `Page<DocumentAsset>`                                                                                                                                | 无                                                                                                  |
| `GET /api/projects/{projectId}/documents/{documentId}`                         | `projectId`、`documentId` 必填                                                    | 无                                                                                                                                                                                      | `{ document: DocumentAsset; currentVersion: DocumentVersion; bindings: NodeFileBinding[]; actions: ActionCode[] }`                                   | 无                                                                                                  |
| `GET /api/projects/{projectId}/documents/{documentId}/versions`                | `projectId`、`documentId` 必填                                                    | 无                                                                                                                                                                                      | `DocumentVersion[]`                                                                                                                                  | 无                                                                                                  |
| `POST /api/projects/{projectId}/documents/upload-session`                      | `projectId` 必填                                                                  | `{ files: Array<{ fileName: string; fileSize: number; fileType: string }>; sourceOrgId: string; defaultUsage?: string; defaultNodeIds?: number[]; remark?: string }`                    | `{ uploadSessionId: string; uploadUrls: Array<SignedUrl & { fileName: string; documentId: string; documentVersionId: string }>; expiresAt: string }` | 新增 `DocumentAsset/DocumentVersion`；当前前端 mock 可直接置为 `已上传`，真实联调按 `complete` 确认 |
| `POST /api/projects/{projectId}/documents/upload-session/{sessionId}/complete` | `projectId`、`sessionId` 必填                                                     | `{ completedFiles: Array<{ documentVersionId: string; hash: string; fileSize: number }> }`                                                                                              | `{ documents: DocumentAsset[]; versions: DocumentVersion[]; ocrTaskIds: string[] }`                                                                  | 文件变为 `已上传`，创建 OCR 任务                                                                    |
| `POST /api/projects/{projectId}/documents/{documentId}/versions`               | `projectId`、`documentId` 必填                                                    | `{ uploadSessionId: string; replaceCurrent: boolean; remark?: string }`                                                                                                                 | `{ document: DocumentAsset; newVersion: DocumentVersion; previousVersionId: string }`                                                                | 当前版本切换                                                                                        |
| `POST /api/projects/{projectId}/documents/bindings`                            | `projectId` 必填                                                                  | `{ nodeId?: number; nodeIds?: number[]; bindings: Array<{ documentId: string; documentVersionId: string; requirementId?: string; usage: NodeFileBinding['usage']; remark?: string }> }` | `MockMutationResult`，`changed` 按节点返回 `nodes.{nodeId}.status`                                                                                   | 新增或更新挂载，支持跨节点批量挂载，节点进度变化                                                    |
| `GET /api/projects/{projectId}/documents/bindings`                             | `projectId` 必填；`documentId/nodeId/status` 可选                                 | 无                                                                                                                                                                                      | `Page<NodeFileBinding>`                                                                                                                              | 无                                                                                                  |
| `PATCH /api/projects/{projectId}/documents/bindings/{bindingId}`               | `projectId`、`bindingId` 必填                                                     | `{ requirementId?: string; usage?: string; remark?: string }`                                                                                                                           | `{ binding: NodeFileBinding }`                                                                                                                       | 更新挂载字段                                                                                        |
| `DELETE /api/projects/{projectId}/documents/bindings/{bindingId}`              | `projectId`、`bindingId` 必填                                                     | `{ reason?: string }`                                                                                                                                                                   | `MockMutationResult`                                                                                                                                 | 草稿挂载解除                                                                                        |
| `POST /api/projects/{projectId}/documents/{documentId}/withdraw`               | `projectId`、`documentId` 必填                                                    | `{ reason: string }`                                                                                                                                                                    | `MockMutationResult`                                                                                                                                 | 未提交文件变为 `已撤回`                                                                             |
| `POST /api/projects/{projectId}/documents/{documentId}/void`                   | `projectId`、`documentId` 必填                                                    | `{ reason: string }`                                                                                                                                                                    | `MockMutationResult`                                                                                                                                 | 文件变为 `已作废`                                                                                   |
| `POST /api/projects/{projectId}/documents/batch-classify`                      | `projectId` 必填                                                                  | `{ documentVersionIds: string[]; strategy?: 'filename'                                                                                                                                  | 'ocr'                                                                                                                                                | 'ai' }`                                                                                             | `Array<{ documentVersionId: string; suggestedNodeIds: number[]; requirementId?: string; confidence: number; reason: string }>` | 无，前端确认后再绑定 |
| `GET /api/projects/{projectId}/documents/{documentId}/preview-url`             | `projectId`、`documentId` 必填；`versionId` 可选                                  | 无                                                                                                                                                                                      | `SignedUrl & { fileName: string; mimeType: string; pageCount?: number }`                                                                             | 无                                                                                                  |
| `GET /api/projects/{projectId}/documents/{documentId}/download-url`            | `projectId`、`documentId` 必填；`versionId` 可选                                  | 无                                                                                                                                                                                      | `SignedUrl & { fileName: string }`                                                                                                                   | 无                                                                                                  |
| `GET /api/projects/{projectId}/documents/{documentId}/ocr-fields`              | `projectId`、`documentId` 必填；`versionId` 可选                                  | 无                                                                                                                                                                                      | `ExtractedField[]`                                                                                                                                   | 无                                                                                                  |
| `GET /api/projects/{projectId}/documents/{documentId}/review-feedback`         | `projectId`、`documentId` 必填                                                    | 无                                                                                                                                                                                      | `{ opinions: ReviewOpinion[]; rectifications: RectificationPayload[]; evidenceLinks: EvidenceLink[] }`                                               | 无                                                                                                  |

### 22.6 提交、补正、监检动作参数和输出

| 接口                                                                                            | Query/Path                                              | Body                                                                                                                                     | `data` 输出                                                                                                                                                                                                                                                                                                                                                                                                    | Mock 状态变化                                                                        |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- | -------------------- |
| `POST /api/projects/{projectId}/submissions/drafts`                                             | `projectId` 必填                                        | `{ nodeId?: number; nodeIds?: number[]; bindingIds?: string[]; documentVersionIds?: string[]; batchName?: string; remark?: string }`     | `{ draftId: string; savedAt: string; bindingIds: string[] }`                                                                                                                                                                                                                                                                                                                                                   | 草稿保存，不触发审查                                                                 |
| `GET /api/projects/{projectId}/submissions/drafts/{draftId}`                                    | `projectId`、`draftId` 必填                             | 无                                                                                                                                       | `{ draftId: string; projectId: string; nodeIds: number[]; nodes: ProjectTreeNode[]; bindings: NodeFileBinding[]; batchName?: string; remark?: string; savedAt: string }`                                                                                                                                                                                                                                       | 无                                                                                   |
| `GET /api/projects/{projectId}/submissions`                                                     | `projectId` 必填                                        | 无                                                                                                                                       | `{ drafts: SubmissionDraftSummary[]; submissions: SubmissionSummary[] }`，摘要含 `nodeIds/nodeNames/bindingCount/batchName/savedAt/submittedAt/nextStatus/todoCount/withdrawal`                                                                                                                                                                                                                                | 无                                                                                   |
| `POST /api/projects/{projectId}/submissions`                                                    | `projectId` 必填                                        | `{ draftId?: string; bindingIds?: string[]; nodeIds: number[]; batchName?: string; submitterComment?: string }`                          | `{ submissionId: string; snapshotId: string; nextStatus: 'AI 预审中/待审查'; createdTodos: TodoItem[] }`                                                                                                                                                                                                                                                                                                       | 绑定变为 `已提交`，节点进入 AI 或待审查                                              |
| `GET /api/projects/{projectId}/submissions/{submissionId}`                                      | `projectId`、`submissionId` 必填                        | 无                                                                                                                                       | `{ submissionId: string; snapshotId: string; projectId: string; nodeIds: number[]; nodes: ProjectTreeNode[]; bindings: NodeFileBinding[]; batchName?: string; submitterComment?: string; nextStatus: string; submittedAt: string; withdrawal?: { bindingCount: number; reason: string; withdrawnAt: string }; createdTodos: TodoItem[]; changed: Array<{ field: string; before?: unknown; after: unknown }> }` | 无                                                                                   |
| `POST /api/projects/{projectId}/submissions/{submissionId}/withdraw-items`                      | `projectId`、`submissionId` 必填                        | `{ bindingIds?: string[]; documentVersionIds?: string[]; reason: string }`                                                               | `MockMutationResult`                                                                                                                                                                                                                                                                                                                                                                                           | 绑定回到草稿挂载，提交快照写入 `withdrawal` 追溯                                     |
| `POST /api/projects/{projectId}/rectifications`                                                 | `projectId` 必填                                        | `{ rectificationId?: string; nodeId: number; description: string; bindingIds?: string[]; files?: string[]; evidenceLinkIds?: string[] }` | `{ rectification: RectificationPayload; nextStatus: '复审中/待复审'; createdTodos: TodoItem[] }`                                                                                                                                                                                                                                                                                                               | 补正任务变为 `已反馈`                                                                |
| `GET /api/projects/{projectId}/rectifications`                                                  | `projectId` 必填；`nodeId/status/responsibleOrgId` 可选 | 无                                                                                                                                       | `Page<RectificationPayload>`                                                                                                                                                                                                                                                                                                                                                                                   | 无                                                                                   |
| `GET /api/projects/{projectId}/rectifications/{rectificationId}`                                | `projectId`、`rectificationId` 必填                     | 无                                                                                                                                       | `RectificationPayload`                                                                                                                                                                                                                                                                                                                                                                                         | 无                                                                                   |
| `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/attachments`                          | `projectId`、`nodeId` 必填                              | `{ files: Array<{ fileName: string; fileSize?: number; fileType?: string }>; type: '外部查询截图'                                        | '现场照片'                                                                                                                                                                                                                                                                                                                                                                                                     | '监检说明'; bindToRequirementId?: string }`                                          | `{ documents: DocumentAsset[]; bindings: NodeFileBinding[]; evidenceLinks: EvidenceLink[] }` | 新增监检资料、证据链 |
| `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/file-bindings`                        | `projectId`、`nodeId` 必填                              | `{ documentVersionIds: string[]; usage: NodeFileBinding['usage']; requirementId?: string }`                                              | `{ bindings: NodeFileBinding[] }`                                                                                                                                                                                                                                                                                                                                                                              | 监检挂载成功                                                                         |
| `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-recheck`                           | `projectId`、`nodeId` 必填                              | `{ documentVersionIds?: string[]; reason?: string; force?: boolean }`                                                                    | `{ runId: string; status: '排队中'                                                                                                                                                                                                                                                                                                                                                                             | '推理中'                                                                             | '完成'; estimatedSeconds?: number; latestRun?: AiReviewRun }`                                | 创建 AI run          |
| `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-runs`                               | `projectId`、`nodeId` 必填                              | 无                                                                                                                                       | `Page<AiReviewRun>`                                                                                                                                                                                                                                                                                                                                                                                            | 无                                                                                   |
| `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-runs/{runId}`                       | `projectId`、`nodeId`、`runId` 必填                     | 无                                                                                                                                       | `AiReviewRun`                                                                                                                                                                                                                                                                                                                                                                                                  | 无                                                                                   |
| `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/review-opinions`                      | `projectId`、`nodeId` 必填                              | `{ result: ReviewOpinion['result']; opinion: string; basis?: string; riskLevel?: string; evidenceLinkIds: string[]; aiRunId?: string }`  | `{ opinion: ReviewOpinion; nextStatus: '已通过'                                                                                                                                                                                                                                                                                                                                                                | '需补正'                                                                             | '不适用'; createdTodos?: TodoItem[] }`                                                       | 保存人工结论         |
| `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/review-opinions`                       | `projectId`、`nodeId` 必填                              | 无                                                                                                                                       | `Page<ReviewOpinion>`                                                                                                                                                                                                                                                                                                                                                                                          | 无                                                                                   |
| `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-suggestions/{suggestionId}/adopt`  | `projectId`、`nodeId`、`suggestionId` 必填              | `{ result: string; opinion: string; reason: string }`                                                                                    | `{ draftOpinion: ReviewOpinion; auditLogId: string }`                                                                                                                                                                                                                                                                                                                                                          | 仅生成草稿，不改变最终节点状态                                                       |
| `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-suggestions/{suggestionId}/reject` | `projectId`、`nodeId`、`suggestionId` 必填              | `{ reason: string; manualOpinion?: string }`                                                                                             | `MockMutationResult`                                                                                                                                                                                                                                                                                                                                                                                           | AI 建议标记驳回                                                                      |
| `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/actions/return-correction`            | `projectId`、`nodeId` 必填                              | `{ responsibleOrgId: string; deadline: string; requirement: string; evidenceLinkIds?: string[]; bindingIds?: string[] }`                 | `{ rectification: RectificationPayload; nextStatus: '退回补正中'; createdTodos: TodoItem[]; messages: MessageItem[] }`                                                                                                                                                                                                                                                                                         | 节点和绑定变为需补正                                                                 |
| `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/report-review`                        | `projectId`、`nodeId` 必填                              | `{ includeEvidence: boolean; reportScope?: 'currentNode'                                                                                 | 'project' }`                                                                                                                                                                                                                                                                                                                                                                                                   | `{ report: ReportVersion; nextStatus: '报告生成/复核中'; createdTodos: TodoItem[] }` | 创建报告草稿                                                                                 |

### 22.7 证据、标准、日期比对输出

| 接口                                                                            | Query/Path                                         | `data` 输出                 |
| ------------------------------------------------------------------------------- | -------------------------------------------------- | --------------------------- |
| `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/evidence-chain`        | `projectId`、`nodeId` 必填；`runId/opinionId` 可选 | `EvidenceChainPayload`      |
| `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/standards`             | `projectId`、`nodeId` 必填                         | `StandardReference[]`       |
| `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/date-compare`          | `projectId`、`nodeId` 必填                         | `DateComparisonItem[]`      |
| `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/rules/current-version` | `projectId`、`nodeId` 必填                         | `CurrentRuleVersionPayload` |
| `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/review-log`            | `projectId`、`nodeId` 必填                         | `ReviewLogItem[]`           |

```ts
type EvidenceChainPayload = {
  node: ProjectTreeNode;
  links: EvidenceLink[];
  groupedByObject: Array<{
    objectType: EvidenceLink["objectType"];
    links: EvidenceLink[];
  }>;
};

type StandardReference = {
  clauseId: string;
  standardName: string;
  clauseNo: string;
  title: string;
  summary: string;
  effectiveVersion: string;
  evidenceLinkId?: string;
};

type DateComparisonItem = {
  fieldName: string;
  leftLabel: string;
  leftValue: string;
  rightLabel: string;
  rightValue: string;
  result: "覆盖" | "不覆盖" | "缺失" | "待确认";
  evidenceLinkIds: string[];
};

type CurrentRuleVersionPayload = {
  ruleVersion: string;
  promptVersion: string;
  templateId: string;
  publishedAt: string;
  enabledTools: string[];
  outputSchemaVersion: string;
};

type ReviewLogItem = {
  id: string;
  type: "提交" | "AI预审" | "人工审查" | "退回补正" | "复审" | "报告";
  actorName: string;
  result: string;
  createdAt: string;
  evidenceLinkIds?: string[];
};
```

### 22.8 无损检测、建设方、报告归档输出

```ts
type NdtFilm = {
  id: string;
  filmNo: string;
  weldNo: string;
  pipelineNo?: string;
  method: "RT" | "UT" | "MT" | "PT";
  testDate?: string;
  evaluationLevel?: string;
  defectCode?: string;
  status: "草稿" | "待提交" | "待审查" | "需补正" | "已通过";
  actions: ActionCode[];
};

type NdtReport = {
  id: string;
  reportNo: string;
  method: NdtFilm["method"];
  fileId: string;
  relatedFilmIds: string[];
  status: NdtFilm["status"];
  conclusion?: string;
  actions: ActionCode[];
};

type NdtRecord = {
  id: string;
  projectId: string;
  nodeId: number;
  recordNo: string;
  filmId?: string;
  reportId?: string;
  weldNo: string;
  pipelineNo?: string;
  method: NdtFilm["method"];
  testDate: string;
  evaluatorName: string;
  result: "合格" | "不合格" | "待复核";
  sampleStatus: "未抽查" | "已抽查" | "需复核";
  conclusion?: string;
  importedAt: string;
  actions: ActionCode[];
};

type NdtRecordImportPayload = {
  imported: number;
  failed: Array<{ row: number; reason: string }>;
  records: NdtRecord[];
};

type NdtReportDetailPayload = {
  report: NdtReport;
  films: NdtFilm[];
  records: NdtRecord[];
  document?: DocumentAsset;
  feedback: NdtFeedback[];
};

type NdtFeedbackDetailPayload = {
  feedback: NdtFeedback;
  reports: NdtReport[];
  films: NdtFilm[];
  records: NdtRecord[];
  evidenceLinks: EvidenceLink[];
  timeline: Array<{
    title: string;
    actorName: string;
    status: string;
    createdAt: string;
    comment?: string;
  }>;
};

type ExportTask = {
  id: string;
  projectId?: string;
  exportType:
    | "report"
    | "archive-package"
    | "evidence-package"
    | "document"
    | "config-package";
  status: "排队中" | "生成中" | "可下载" | "失败" | "已过期";
  progress: number;
  fileName: string;
  fileSize?: number;
  downloadUrl?: string;
  createdAt: string;
  finishedAt?: string;
  expiresAt?: string;
  errorMessage?: string;
};

type ArchiveItemDetailPayload = {
  item: ArchiveItem;
  preview?: DocumentPreviewPayload;
  download?: SignedUrlPayload;
  report?: ReportVersion;
  document?: DocumentAsset;
  evidenceLinks: EvidenceLink[];
  relatedExportTasks: ExportTask[];
};

type OwnerDashboardPayload = {
  project: Project;
  metrics: WorkbenchSummaryPayload["metrics"];
  nodeSummary: Array<{
    nodeId: number;
    nodeName: string;
    status: NodeStatus;
    fileCount: number;
    correctionCount: number;
  }>;
  latestReports: ReportVersion[];
  readonly: true;
};

type ReportDetailPayload = {
  report: ReportVersion;
  sections: Array<{
    key: string;
    title: string;
    content: string;
    evidenceLinkIds: string[];
  }>;
  evidenceLinks: EvidenceLink[];
  reviewTrail: Array<{
    title: string;
    actorName: string;
    result: string;
    createdAt: string;
    comment?: string;
  }>;
  versionHistory: Array<{
    id: string;
    versionNo: string;
    status: ReportVersion["status"];
    generatedAt: string;
    summary: string;
  }>;
};
```

| 接口                                                                 | Body/Query                                                                                              | `data` 输出                                                                              | Mock 状态变化              |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | -------------------------- |
| `GET /api/projects/{projectId}/ndt/summary`                          | `projectId` 必填                                                                                        | `WorkbenchSummaryPayload`                                                                | 无                         |
| `GET /api/projects/{projectId}/ndt/films`                            | `status/method/keyword/page/pageSize` 可选                                                              | `Page<NdtFilm>`                                                                          | 无                         |
| `POST /api/projects/{projectId}/ndt/films`                           | `{ filmNo: string; weldNo: string; method: string; testDate?: string }`                                 | `{ film: NdtFilm }`                                                                      | 新增底片                   |
| `PATCH /api/projects/{projectId}/ndt/films/{filmId}`                 | `Partial<NdtFilm>`                                                                                      | `{ film: NdtFilm }`                                                                      | 更新底片                   |
| `POST /api/projects/{projectId}/ndt/films/import`                    | `{ fileId?: string; rows?: NdtFilm[] }`                                                                 | `{ imported: number; failed: Array<{ row: number; reason: string }>; films: NdtFilm[] }` | 批量新增                   |
| `GET /api/projects/{projectId}/ndt/records`                          | `filmId/reportId/sampleStatus/page/pageSize` 可选                                                       | `Page<NdtRecord>`                                                                        | 无                         |
| `POST /api/projects/{projectId}/ndt/records/import`                  | `{ fileId?: string; nodeId: number; rows?: Partial<NdtRecord>[] }`                                      | `NdtRecordImportPayload`                                                                 | 批量新增并生成导入消息     |
| `GET /api/projects/{projectId}/ndt/reports`                          | `status/method/page/pageSize` 可选                                                                      | `Page<NdtReport>`                                                                        | 无                         |
| `GET /api/projects/{projectId}/ndt/reports/{reportId}`               | `reportId` 必填                                                                                         | `NdtReportDetailPayload`                                                                 | 无                         |
| `POST /api/projects/{projectId}/ndt/reports/upload-session`          | `{ files: Array<{ fileName: string; fileSize: number; fileType: string }>; relatedFilmIds?: string[] }` | `{ uploadSessionId: string; uploadUrls: SignedUrl[] }`                                   | 新建报告文件；失败不写状态 |
| `POST /api/projects/{projectId}/ndt/submissions`                     | `{ reportIds: string[]; filmIds?: string[]; nodeId: number }`                                           | `{ submissionId: string; nextStatus: '待审查'; createdTodos: TodoItem[] }`               | 检测资料提交               |
| `POST /api/projects/{projectId}/ndt/rectifications`                  | `{ rectificationId: string; description: string; reportIds?: string[]; filmIds?: string[] }`            | `{ rectification: RectificationPayload; nextStatus: '复审中' }`                          | 补正反馈                   |
| `GET /api/projects/{projectId}/ndt/inspection-feedback`              | `status/page/pageSize` 可选                                                                             | `Page<NdtFeedback>`                                                                      | 无                         |
| `GET /api/projects/{projectId}/ndt/inspection-feedback/{feedbackId}` | `feedbackId` 必填                                                                                       | `NdtFeedbackDetailPayload`                                                               | 无                         |
| `GET /api/projects/{projectId}/owner/dashboard`                      | `projectId` 必填                                                                                        | `OwnerDashboardPayload`                                                                  | 无                         |
| `GET /api/projects/{projectId}/owner/node-summary`                   | `projectId` 必填                                                                                        | `OwnerDashboardPayload['nodeSummary']`                                                   | 无                         |
| `GET /api/projects/{projectId}/owner/reports`                        | `projectId` 必填                                                                                        | `ReportVersion[]`                                                                        | 无                         |
| `GET /api/projects/{projectId}/reports`                              | `status/page/pageSize` 可选                                                                             | `Page<ReportVersion>`                                                                    | 无                         |
| `GET /api/projects/{projectId}/reports/{reportId}`                   | `reportId` 必填                                                                                         | `ReportDetailPayload`                                                                    | 无                         |
| `PATCH /api/projects/{projectId}/reports/{reportId}`                 | `{ sections?: unknown[]; remark?: string }`                                                             | `{ report: ReportVersion }`                                                              | 保存报告草稿               |
| `POST /api/projects/{projectId}/reports/{reportId}/export`           | `{ format: 'docx' \| 'pdf' }`                                                                           | `{ exportId: string; report: ReportVersion }`                                            | 创建可查询导出任务         |
| `POST /api/projects/{projectId}/reports/{reportId}/archive`          | `{ archiveNote?: string }`                                                                              | `{ report: ReportVersion; nextStatus: '已归档' }`                                        | 报告归档                   |
| `GET /api/projects/{projectId}/archive`                              | `keyword/nodeId/page/pageSize` 可选                                                                     | `Page<ArchiveItem>`                                                                      | 无                         |
| `GET /api/projects/{projectId}/archive/{archiveItemId}`              | `archiveItemId` 必填                                                                                    | `ArchiveItemDetailPayload`                                                               | 无                         |
| `GET /api/projects/{projectId}/archive/package`                      | `projectId` 必填                                                                                        | `ArchivePackagePayload`                                                                  | 创建可查询导出任务         |
| `GET /api/projects/{projectId}/archive/evidence-package`             | `nodeId` 可选                                                                                           | `ArchivePackagePayload`                                                                  | 创建可查询导出任务         |
| `GET /api/projects/{projectId}/export-tasks/{exportId}`              | `exportId` 必填                                                                                         | `{ task: ExportTask }`                                                                   | 无                         |

### 22.9 AI 知识库和后台配置输出

```ts
type KnowledgeOverviewPayload = {
  metrics: WorkbenchSummaryPayload["metrics"];
  libraries: Array<{
    key: string;
    name: string;
    fileCount: number;
    chunkCount: number;
    vectorCount: number;
    indexVersion: string;
    status: string;
    updatedAt: string;
  }>;
};

type KnowledgeSource = {
  id: string;
  name: string;
  sourceType: "standard" | "project-file" | "rule" | "manual";
  version?: string;
  status: KnowledgeStatus;
  fileCount: number;
  chunkCount: number;
  vectorStatus: VectorStatus;
  updatedAt: string;
  actions: ActionCode[];
};

type KnowledgeSourceSavePayload = {
  name: string;
  sourceType: KnowledgeSource["sourceType"];
  version?: string;
  status?: KnowledgeStatus;
  fileCount?: number;
  chunkCount?: number;
  vectorStatus?: VectorStatus;
};

type KnowledgeFile = {
  id: string;
  fileName: string;
  sourceId: string;
  projectId?: string;
  nodeId?: number;
  documentVersionId?: string;
  ocrStatus: OcrStatus;
  sliceStatus: SliceStatus;
  vectorStatus: VectorStatus;
  chunkCount: number;
  vectorCount: number;
  updatedAt: string;
};

type KnowledgeTask = {
  id: string;
  taskType: "ocr" | "slice" | "vector" | "reindex";
  targetType: "source" | "file" | "project";
  targetId: string;
  status: "排队中" | "运行中" | "成功" | "失败" | "已取消";
  progress: number;
  errorMessage?: string;
  createdAt: string;
  finishedAt?: string;
};

type KnowledgeRuleVersion = {
  id: string;
  name: string;
  ruleKey: string;
  version: string;
  status: "草稿" | "待发布" | "已发布" | "已回滚";
  nodeIds: number[];
  promptVersion: string;
  outputSchemaVersion: string;
  description?: string;
  publishedAt?: string;
  updatedAt: string;
  actions: ActionCode[];
};

type KnowledgeRuleVersionDiffChange = {
  field: "version" | "status" | "nodes" | "prompt" | "schema" | "description";
  label: string;
  before?: unknown;
  after?: unknown;
  severity: "info" | "warning";
  changeType: "added" | "changed" | "removed";
};

type KnowledgeRuleVersionDiffPayload = {
  base: KnowledgeRuleVersion;
  target: KnowledgeRuleVersion;
  comparedAt: string;
  summary: {
    added: number;
    changed: number;
    removed: number;
    warning: number;
  };
  changes: KnowledgeRuleVersionDiffChange[];
};

type KnowledgeConfig = {
  embeddingModel: string;
  chunkSize: number;
  chunkOverlap: number;
  topKDefault: number;
  rerankEnabled: boolean;
  evidenceStrictMode: boolean;
  autoReindex: boolean;
  retentionDays: number;
  updatedBy: string;
  updatedAt: string;
};

type RuleTemplate = {
  id: string;
  name: string;
  nodeScope: number[];
  version: string;
  status: RuleStatus;
  promptVersion?: string;
  outputSchemaVersion: string;
  updatedAt: string;
};
```

| 接口范围                                                                               | 参数/Body                                                                                                                                                                                                            | `data` 输出                                                                                                            | Mock 状态变化                                                           |
| -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `GET /api/knowledge/overview`                                                          | 无                                                                                                                                                                                                                   | `KnowledgeOverviewPayload`                                                                                             | 无                                                                      |
| `GET /api/knowledge/sources`                                                           | `keyword/sourceType/status/page/pageSize` 可选                                                                                                                                                                       | `Page<KnowledgeSource>`                                                                                                | 无                                                                      |
| `POST /api/knowledge/sources`                                                          | `KnowledgeSourceSavePayload`，`name` 必填                                                                                                                                                                            | `{ source: KnowledgeSource; auditLogId: string }`                                                                      | 新增知识源，写审计                                                      |
| `GET /api/knowledge/sources/{sourceId}`                                                | `sourceId` 必填                                                                                                                                                                                                      | `{ source: KnowledgeSource }`                                                                                          | 无                                                                      |
| `PUT/PATCH /api/knowledge/sources/{sourceId}`                                          | `Partial<KnowledgeSourceSavePayload>`                                                                                                                                                                                | `{ source: KnowledgeSource; auditLogId: string }`                                                                      | 更新知识源，写审计                                                      |
| `POST /api/knowledge/sources/{sourceId}/enable`                                        | `{ reason?: string }`                                                                                                                                                                                                | `{ source: KnowledgeSource; auditLogId: string }`                                                                      | 状态变为 `启用`，写审计                                                 |
| `POST /api/knowledge/sources/{sourceId}/disable`                                       | `{ reason?: string }`                                                                                                                                                                                                | `{ source: KnowledgeSource; auditLogId: string }`                                                                      | 状态变为 `停用`，写审计                                                 |
| `GET /api/knowledge/project-files`                                                     | `projectId/nodeId/status/page/pageSize` 可选                                                                                                                                                                         | `Page<KnowledgeFile>`                                                                                                  | 无                                                                      |
| `GET /api/knowledge/files/{fileId}`                                                    | `fileId` 必填                                                                                                                                                                                                        | `{ file: KnowledgeFile; document?: DocumentAsset; latestTask?: KnowledgeTask; vectorSummary: KnowledgeVectorSummary }` | 无                                                                      |
| `GET /api/knowledge/files/{fileId}/chunks`                                             | `fileId` 必填，`page/pageSize` 可选                                                                                                                                                                                  | `Page<KnowledgeChunk>`                                                                                                 | 无                                                                      |
| `GET /api/knowledge/files/{fileId}/vectors`                                            | `fileId` 必填                                                                                                                                                                                                        | `KnowledgeVectorSummary`                                                                                               | 无                                                                      |
| `GET /api/knowledge/files/{fileId}/reasoning-references`                               | `fileId` 必填，`page/pageSize` 可选                                                                                                                                                                                  | `Page<KnowledgeReasoningReference>`                                                                                    | 无                                                                      |
| `GET /api/knowledge/tasks`                                                             | `taskType/status/page/pageSize` 可选                                                                                                                                                                                 | `Page<KnowledgeTask>`                                                                                                  | 无                                                                      |
| `POST /api/knowledge/tasks/{taskId}/retry`                                             | `{ reason?: string }`                                                                                                                                                                                                | `{ task: KnowledgeTask }`                                                                                              | 新建重试任务，写审计/消息                                               |
| `POST /api/knowledge/tasks/{taskId}/cancel`                                            | `{ reason?: string }`                                                                                                                                                                                                | `{ task: KnowledgeTask }`                                                                                              | 取消排队任务，写审计                                                    |
| `POST /api/knowledge/files/{fileId}/reindex`                                           | `{ force?: boolean }`                                                                                                                                                                                                | `{ task: KnowledgeTask }`                                                                                              | 创建重建索引任务                                                        |
| `POST /api/knowledge/reindex`                                                          | `{ scope: "all" \| "project" \| "source"; projectId?: string; sourceId?: string }`                                                                                                                                   | `{ taskIds: string[] }`                                                                                                | 批量创建索引任务                                                        |
| `GET /api/knowledge/config`                                                            | 无                                                                                                                                                                                                                   | `{ config: KnowledgeConfig; updatedAt: string }`                                                                       | 无                                                                      |
| `PUT/PATCH /api/knowledge/config`                                                      | `Partial<KnowledgeConfig>`                                                                                                                                                                                           | `{ config: KnowledgeConfig; updatedAt: string; auditLogId: string }`                                                   | 更新配置，写审计                                                        |
| `GET /api/knowledge/audit-logs`                                                        | `keyword/objectType/result/page/pageSize` 可选                                                                                                                                                                       | `Page<AuditLog>`                                                                                                       | 无                                                                      |
| `POST /api/knowledge/retrieval-test`                                                   | `{ question: string; scope: string[]; projectId?: string; nodeId?: number; topK: number }`                                                                                                                           | `{ answerDraft: string; hits: EvidenceLink[]; latencyMs: number; usedIndexVersions: string[] }`                        | 无                                                                      |
| `GET /api/rules/versions`                                                              | `keyword/status/page/pageSize` 可选                                                                                                                                                                                  | `Page<KnowledgeRuleVersion>`                                                                                           | 无                                                                      |
| `GET /api/rules/versions/{versionId}/diff`                                             | `targetVersionId/targetVersion` 可选；为空时默认取同 `ruleKey` 的已发布版本或最近可比版本                                                                                                                            | `KnowledgeRuleVersionDiffPayload`                                                                                      | 无                                                                      |
| `POST /api/rules/versions/{versionId}/publish`                                         | `{ reason: string; effectiveAt?: string }`                                                                                                                                                                           | `MockMutationResult & { rule: KnowledgeRuleVersion }`                                                                  | 当前版本变为 `已发布`，同 `ruleKey` 其他已发布版本变为 `已回滚`，写审计 |
| `POST /api/rules/versions/{versionId}/rollback`                                        | `{ reason: string; targetVersion: string }`                                                                                                                                                                          | `MockMutationResult & { rule: KnowledgeRuleVersion; target: KnowledgeRuleVersion }`                                    | 当前版本变为 `已回滚`，目标版本变为 `已发布`，写审计                    |
| `GET /api/reasoning/logs`                                                              | `projectId/nodeId/status/page/pageSize` 可选                                                                                                                                                                         | `Page<AiReviewRun>`                                                                                                    | 无                                                                      |
| `GET /api/reasoning/logs/{logId}`                                                      | `logId` 必填                                                                                                                                                                                                         | `ReasoningLogDetailPayload`                                                                                            | 无                                                                      |
| `GET /api/reasoning/logs/{logId}/evidence`                                             | `logId` 必填                                                                                                                                                                                                         | `EvidenceLink[]`                                                                                                       | 无                                                                      |
| `POST /api/llm/compare`                                                                | `{ question: string; modelCodes: string[]; projectId?: string; nodeId?: number; evidenceLinkIds?: string[] }`                                                                                                        | `LlmComparePayload`                                                                                                    | 生成对比记录，写审计                                                    |
| `GET /api/llm/compare-runs`                                                            | `projectId/nodeId/page/pageSize` 可选                                                                                                                                                                                | `Page<LlmCompareRunSummary>`                                                                                           | 无                                                                      |
| `GET /api/llm/compare-runs/{runId}`                                                    | `runId` 必填                                                                                                                                                                                                         | `LlmComparePayload`                                                                                                    | 无                                                                      |
| 后台配置 `tree-nodes/node-role-mappings/org-units/users/roles/workflow-state-machines` | 列表 query；新增/编辑使用对应实体 `Partial<T>`                                                                                                                                                                       | 列表统一 `Page<T>`；保存统一 `{ item: T }` 或 `MockMutationResult`                                                     | 配置状态变化，必须写审计                                                |
| `GET /api/admin/config-overview`                                                       | 无                                                                                                                                                                                                                   | `AdminConfigOverviewPayload`                                                                                           | 无                                                                      |
| `GET /api/admin/integration-contract`                                                  | `module?: "all" \| "workbench" \| "documents" \| "submissions" \| "inspection" \| "ndt-owner-report" \| "knowledge-admin"`；`status?: "all" \| "已对齐" \| "待后端确认" \| "前端缺失" \| "后端缺失" \| "命名不一致"` | `IntegrationContractPayload`                                                                                           | 无                                                                      |
| `POST /api/admin/config-diff/preview`                                                  | `AdminConfigChangePayload`                                                                                                                                                                                           | `AdminConfigDiffPayload`                                                                                               | 仅预览差异，不写入                                                      |
| `POST /api/admin/config-items/{target}`                                                | `target` 支持 `todo-rule/message-template/tool-source/field-mapping`；Body: `AdminConfigCreatePayload`                                                                                                               | `AdminConfigSaveResult`                                                                                                | 新增细项配置，写审计并返回创建差异                                      |
| `PUT /api/admin/config-items/{target}/{id}`                                            | `target/id` 必填；Body: `AdminConfigChangePayload`                                                                                                                                                                   | `AdminConfigSaveResult`                                                                                                | 更新权限矩阵、节点模板、流程状态机或细项配置，写审计                    |
| `POST /api/admin/config-overview/publish`                                              | `{ scope: "all" \| "permission" \| "workflow" \| "node-template" \| "rule"; reason: string }`                                                                                                                        | `AdminPublishConfigPayload`                                                                                            | 生成配置版本、联动影响摘要和审计                                        |
| `GET /api/admin/todo-rules`                                                            | `keyword/page/pageSize` 可选                                                                                                                                                                                         | `Page<AdminTodoRule>`                                                                                                  | 无                                                                      |
| `POST /api/admin/todo-rules`                                                           | `AdminTodoRuleValues & { reason?: string }`                                                                                                                                                                          | `{ item: AdminTodoRule; auditLogId: string }`                                                                          | 新增待办规则，写审计                                                    |
| `PATCH /api/admin/todo-rules/{ruleId}`                                                 | `Partial<AdminTodoRuleValues> & { reason?: string }`                                                                                                                                                                 | `{ item: AdminTodoRule; auditLogId: string }`                                                                          | 更新待办规则，写审计                                                    |
| `GET /api/admin/message-templates`                                                     | `keyword/page/pageSize` 可选                                                                                                                                                                                         | `Page<AdminMessageTemplate>`                                                                                           | 无                                                                      |
| `POST /api/admin/message-templates`                                                    | `AdminMessageTemplateValues & { reason?: string }`                                                                                                                                                                   | `{ item: AdminMessageTemplate; auditLogId: string }`                                                                   | 新增消息模板，写审计                                                    |
| `PATCH /api/admin/message-templates/{templateId}`                                      | `Partial<AdminMessageTemplateValues> & { reason?: string }`                                                                                                                                                          | `{ item: AdminMessageTemplate; auditLogId: string }`                                                                   | 更新消息模板，写审计                                                    |
| `GET /api/admin/tool-sources`                                                          | `keyword/page/pageSize` 可选                                                                                                                                                                                         | `Page<AdminToolSource>`                                                                                                | 无                                                                      |
| `POST /api/admin/tool-sources`                                                         | `AdminToolSourceValues & { reason?: string }`                                                                                                                                                                        | `{ item: AdminToolSource; auditLogId: string }`                                                                        | 新增工具源，写审计                                                      |
| `PATCH /api/admin/tool-sources/{toolSourceId}`                                         | `Partial<AdminToolSourceValues> & { reason?: string }`                                                                                                                                                               | `{ item: AdminToolSource; auditLogId: string }`                                                                        | 更新工具源，写审计                                                      |
| `GET /api/admin/field-mappings`                                                        | `keyword/page/pageSize` 可选                                                                                                                                                                                         | `Page<AdminFieldMapping>`                                                                                              | 无                                                                      |
| `POST /api/admin/field-mappings`                                                       | `AdminFieldMappingValues & { reason?: string }`                                                                                                                                                                      | `{ item: AdminFieldMapping; auditLogId: string }`                                                                      | 新增字段映射，写审计                                                    |
| `PATCH /api/admin/field-mappings/{mappingId}`                                          | `Partial<AdminFieldMappingValues> & { reason?: string }`                                                                                                                                                             | `{ item: AdminFieldMapping; auditLogId: string }`                                                                      | 更新字段映射，写审计                                                    |
| 规则配置 `rules/templates/rules/versions/prompts/tool-sources/field-mappings`          | 列表 query；发布/回滚 body `{ reason: string }`                                                                                                                                                                      | 列表 `Page<RuleTemplate>` 或对应实体；发布/回滚 `MockMutationResult`                                                   | 版本状态变化                                                            |
| 审计 `audit-logs`                                                                      | `actorId/action/objectType/projectId/dateRange/page/pageSize` 可选                                                                                                                                                   | `Page<AuditLog>`                                                                                                       | 无                                                                      |

后台配置发布必须返回联动追溯信息，前端用于展示“发布后哪些配置域已同步、哪些仍需复核”。该接口会写入配置版本、审计日志、工作台通知消息；当存在 `需复核` 影响项时，还会为监检角色生成配置复核待办，但不直接代替业务角色执行审查、提交或归档动作。

```ts
type AdminPublishImpact = {
  domain:
    | "permission"
    | "workflow"
    | "node-template"
    | "rule"
    | "todo-rule"
    | "message-template"
    | "tool-source"
    | "field-mapping";
  label: string;
  affectedCount: number;
  status: "已同步" | "需复核";
  trace: string;
};

type AdminPublishConfigPayload = {
  publishId: string;
  status: "已发布";
  version: string;
  auditLogId: string;
  publishedAt: string;
  impactSummary: {
    totalAffected: number;
    warningCount: number;
    linkedProjects: number;
    pushedMessages: number;
    reviewTodos: number;
  };
  impacts: AdminPublishImpact[];
};
```

发布成功后的最低跨页面联动要求：

- 每个非归档项目生成 1 条工作台消息，标题包含发布版本，内容包含发布范围、影响项数量和发布原因。
- 当 `warningCount > 0` 时，每个非归档项目生成 1 条监检角色配置复核待办，待办标题应能追溯到字段映射或其它需复核配置域。
- 管理后台发布卡片和发布联动追溯弹窗必须展示 `pushedMessages/reviewTodos` 数量，监检工作台的“消息/待办”全局入口必须能读取这些写回结果。

联调字段差异清单用于 mock 阶段和真实后端联调前的字段对账，不产生业务状态写入。前端必须能按 `module` 和 `status` 筛选，并能从返回值中直接渲染模块统计、阻塞项数量和字段差异表。

```ts
type IntegrationContractModule =
  | "workbench"
  | "documents"
  | "submissions"
  | "inspection"
  | "ndt-owner-report"
  | "knowledge-admin";

type IntegrationContractStatus =
  | "已对齐"
  | "待后端确认"
  | "前端缺失"
  | "后端缺失"
  | "命名不一致";

type IntegrationContractField = {
  id: string;
  module: IntegrationContractModule;
  moduleLabel: string;
  endpoint: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  frontendField: string;
  backendField: string;
  required: boolean;
  status: IntegrationContractStatus;
  severity: "info" | "warning" | "danger";
  owner: string;
  note: string;
  updatedAt: string;
};

type IntegrationContractPayload = {
  summary: {
    total: number;
    aligned: number;
    pending: number;
    blockers: number;
  };
  modules: Array<{
    module: IntegrationContractModule;
    label: string;
    total: number;
    aligned: number;
    pending: number;
    blockers: number;
  }>;
  fields: IntegrationContractField[];
  generatedAt: string;
};
```

管理后台细项配置的 mock 类型：

```ts
type AdminTodoRule = {
  id: string;
  name: string;
  triggerStatus: string;
  assigneeRole: RoleCode;
  deadlineHours: number;
  enabled: boolean;
  updatedAt: string;
};

type AdminMessageTemplate = {
  id: string;
  scene: string;
  channel: "站内信" | "短信" | "邮件";
  titleTemplate: string;
  contentTemplate: string;
  enabled: boolean;
  updatedAt: string;
};

type AdminToolSource = {
  id: string;
  name: string;
  toolType: "external-query" | "ocr" | "signature" | "archive";
  endpoint: string;
  authMode: "none" | "token" | "signature";
  status: "启用" | "停用" | "异常";
  updatedAt: string;
};

type AdminFieldMapping = {
  id: string;
  nodeId: number;
  fieldName: string;
  sourceField: string;
  targetField: string;
  required: boolean;
  confidenceThreshold: number;
  updatedAt: string;
};
```

### 22.10 搜索、待办、消息、导出输出

| 接口                                       | 参数/Body                                                                                                                                                            | `data` 输出                                                              | Mock 状态变化              |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | -------------------------- |
| `GET /api/search`                          | `keyword` 必填；`projectId/type/page/pageSize` 可选                                                                                                                  | `Page<SearchResult>`                                                     | 无                         |
| `GET /api/todos`                           | `role/projectId/status/page/pageSize` 可选                                                                                                                           | `Page<TodoItem>`                                                         | 无                         |
| `GET /api/todos/{todoId}`                  | `todoId` 必填                                                                                                                                                        | `TodoItem & { relatedObject?: unknown; evidenceLinks?: EvidenceLink[] }` | 无                         |
| `POST /api/todos/{todoId}/complete`        | `{ result?: string; comment?: string }`                                                                                                                              | `MockMutationResult`                                                     | 待办关闭                   |
| `POST /api/todos/{todoId}/defer`           | `{ deferTo: string; reason: string }`                                                                                                                                | `{ todo: TodoItem }`                                                     | 待办延期                   |
| `GET /api/messages`                        | `projectId/read/page/pageSize` 可选                                                                                                                                  | `Page<MessageItem>`                                                      | 无                         |
| `POST /api/messages/{messageId}/read`      | 无                                                                                                                                                                   | `MockMutationResult`                                                     | 消息已读                   |
| `POST /api/messages/read-all`              | `{ projectId?: string }`                                                                                                                                             | `{ affectedCount: number }`                                              | 消息全部已读               |
| `POST /api/admin/config-export`            | `{ scope: "all" \| "permission" \| "workflow" \| "node-template" \| "rule"; includeAudit?: boolean; reason?: string }`                                               | `{ exportId: string; task: ExportTask; auditLogId: string }`             | 创建配置包导出任务，写审计 |
| `POST /api/exports`                        | `{ exportType: "status-summary" \| "node-list" \| "document-list" \| "config-package" \| "archive-package"; projectId?: string; filters?: Record<string, unknown> }` | `{ exportId: string; status: "排队中"; createdAt: string }`              | 创建导出任务               |
| `GET /api/exports/{exportId}`              | `exportId` 必填                                                                                                                                                      | `{ task: ExportTask }`                                                   | 无                         |
| `GET /api/exports/{exportId}/download-url` | `exportId` 必填                                                                                                                                                      | `SignedUrl`                                                              | 无                         |
| `GET /api/downloads/{fileId}/signed-url`   | `fileId` 必填                                                                                                                                                        | `SignedUrl`                                                              | 无                         |

### 22.11 Mock 必须覆盖的错误态

| 错误码                       | 前端触发方式                                           | 期望前端表现                                             |
| ---------------------------- | ------------------------------------------------------ | -------------------------------------------------------- |
| `VALIDATION_ERROR`           | 必填 body 字段为空，如 `opinion`、`reason`、`deadline` | 表单字段提示，不关闭弹窗                                 |
| `FORBIDDEN`                  | `role=owner` 调用写接口，或无节点权限                  | 按钮禁用或 toast 权限不足                                |
| `NOT_FOUND`                  | 不存在的 `projectId/documentId/nodeId`                 | 空状态或返回列表页                                       |
| `REPORT_NOT_FOUND`           | 报告详情或复核版本已被移除                             | 报告详情抽屉就近提示，保留抽屉并支持重试                 |
| `ARCHIVE_NOT_FOUND`          | 归档资料详情已被移除或无权访问                         | 归档资料详情抽屉就近提示，保留抽屉并支持重试             |
| `EXPORT_TASK_NOT_FOUND`      | 导出任务不存在、已过期或无权访问                       | 导出任务详情抽屉就近提示，保留抽屉并支持重试             |
| `CONFLICT`                   | 已归档项目继续编辑、已提交项重复提交                   | 展示状态冲突并刷新详情                                   |
| `FILE_TOO_LARGE`             | 上传文件超过限制                                       | 上传抽屉就近提示，保留文件列表并支持调整后重试           |
| `UNSUPPORTED_FILE_TYPE`      | 上传不支持格式                                         | 上传抽屉就近提示，保留文件列表并支持调整后重试           |
| `NDT_FILE_TOO_LARGE`         | 无损检测报告或影像包超过限制                           | NDT 报告上传表单就近提示，保留文件名和关联底片并支持重试 |
| `UNSUPPORTED_NDT_FILE_TYPE`  | 无损检测报告或影像包格式不支持                         | NDT 报告上传表单就近提示，保留文件名和关联底片并支持重试 |
| `NDT_FILM_REQUIRED`          | 新增无损检测底片时缺少底片编号、焊口编号或检测方法     | NDT 底片表单就近提示，保留已填字段并支持重试             |
| `NDT_RECORD_REQUIRED`        | 导入无损检测记录时缺少记录编号、焊口编号或检测方法     | NDT 记录导入表单就近提示，保留已填字段并支持重试         |
| `NDT_REPORT_REQUIRED`        | 提交无损检测资料时没有可提交检测报告                   | NDT 操作区就近提示，保留当前报告/底片集合并支持重试      |
| `NDT_RECTIFICATION_REQUIRED` | 提交无损检测补正反馈时缺少反馈事项或说明               | NDT 补正表单就近提示，保留反馈事项和说明并支持重试       |
| `TASK_RUNNING`               | 重复触发 AI recheck、reindex、export                   | 展示已有任务进度                                         |
| `ARCHIVED_READONLY`          | 归档项目调用任何 mutation                              | 展示只读原因                                             |
| `ETAG_CONFLICT`              | 保存草稿、提交批次、配置保存时携带过期版本             | 保留弹窗输入，就近提示并支持重试                         |
| `EMPTY_BINDINGS`             | 保存挂载时未选择资料、版本或目标节点                   | 保留挂载弹窗选择，就近提示并支持重试                     |
| `EMPTY_NODE_PACKAGE`         | 未选择资料且节点范围内没有可提交挂载资料               | 提示补充或重新选择资料，不关闭弹窗                       |
| `WITHDRAW_LOCKED`            | 撤回已通过、锁定或不可撤回资料                         | 保留撤回原因，就近提示并支持重试                         |

上传会话创建失败时，前端必须保留本次抽屉内 `files[].fileName/fileType/fileSize`，并在抽屉内展示 `data.reason` 映射后的恢复建议；`FILE_TOO_LARGE`、`UNSUPPORTED_FILE_TYPE`、`TASK_RUNNING`、`ETAG_CONFLICT` 等错误不得关闭上传抽屉，用户可调整文件或点击重试创建。

无损检测报告上传会话创建失败时，前端必须保留 `files[].fileName/fileType/fileSize` 和 `relatedFilmIds`，并在 NDT 报告上传表单内展示 `data.reason` 映射后的恢复建议；`NDT_FILE_TOO_LARGE`、`UNSUPPORTED_NDT_FILE_TYPE`、`TASK_RUNNING`、`ETAG_CONFLICT` 等错误不得清空表单，用户可调整报告文件或点击重试上传会话。

无损检测底片新增失败时，前端必须保留当前 `filmNo/weldNo/method/pipelineNo/testDate`，并在 NDT 底片表单内展示 `data.reason` 映射后的恢复建议；`TASK_RUNNING`、`ETAG_CONFLICT`、`NDT_FILM_REQUIRED` 等错误不得清空表单，用户可调整底片信息或点击重试新增底片。

无损检测记录导入失败时，前端必须保留当前 `rows[]` 和表单中的 `recordNo/weldNo/method/pipelineNo/result`，并在 NDT 记录导入表单内展示 `data.reason` 映射后的恢复建议；`TASK_RUNNING`、`ETAG_CONFLICT`、`NDT_RECORD_REQUIRED` 等错误不得清空表单，用户可调整记录信息或点击重试导入记录。

无损检测资料提交失败时，前端必须保留当前待提交 `reportIds/filmIds` 对应的报告和底片列表，并在 NDT 操作区展示 `data.reason` 映射后的恢复建议；`TASK_RUNNING`、`ETAG_CONFLICT`、`NDT_REPORT_REQUIRED` 等错误不得刷新掉待提交上下文，用户可等待任务结束、补充报告或点击重试提交。

无损检测补正反馈提交失败时，前端必须保留当前 `rectificationId/description/reportIds/filmIds`，并在 NDT 补正反馈表单内展示 `data.reason` 映射后的恢复建议；`TASK_RUNNING`、`ETAG_CONFLICT`、`NDT_RECTIFICATION_REQUIRED` 等错误不得清空反馈说明，用户可调整说明或点击重试补正反馈。

报告复核详情、归档资料详情和导出任务详情加载失败时，前端必须保留当前抽屉和最近一次请求 ID，并在抽屉内展示 `data.reason` 映射后的恢复建议；`REPORT_NOT_FOUND`、`ARCHIVE_NOT_FOUND`、`EXPORT_TASK_NOT_FOUND`、`FORBIDDEN`、`TASK_RUNNING` 等错误不得退回列表页，用户可点击抽屉内重试重新加载当前对象。

### 22.12 是否足够支撑前端 mock 开发

补齐本节后，API 文档已经足够支撑前端 mock 开发，边界如下：

- 足够：页面级 mock、列表/详情 mock、工作台状态流转 mock、权限显隐 mock、AI 审查链路 mock、知识库任务 mock、后台配置 mock。
- 足够：用 MSW/Mock.js/Vite mock 生成固定数据、分页数据、错误态数据和 mutation 后的局部状态变化。
- 第 23 节已补齐字段校验、鉴权 header、幂等键、并发版本、状态机和 mock 种子数据，可作为前端 mock 与真实联调之间的过渡合同。
- 若要生成 SDK，仍建议把第 4、22、23 节拆成 OpenAPI 3.1 YAML；字段规则和状态机按第 23 节落到 schema、headers、responses 和 examples。

## 23. 真实联调前补齐合同

### 23.1 请求头、鉴权、幂等和并发

所有接口都应接受以下请求头。前端 mock 阶段可以只校验 `X-Role`、`X-Project-Id`、`Idempotency-Key` 和 `If-Match`，真实后端必须完整校验。

| Header                          | 必填          | 适用范围               | 说明                                                        |
| ------------------------------- | ------------- | ---------------------- | ----------------------------------------------------------- |
| `Authorization: Bearer <token>` | 是            | 全部接口               | 登录态。mock 可使用固定 token `mock-token`                  |
| `X-Request-Id`                  | 否            | 全部接口               | 前端生成的请求追踪 ID；后端原样写入日志                     |
| `X-Role`                        | 是            | 全部业务接口           | 当前视图角色，值为 `inspection/contractor/ndt/owner/admin`  |
| `X-Project-Id`                  | 条件必填      | 项目域接口             | 路径中已有 `projectId` 时需一致；跨项目管理接口可省略       |
| `Idempotency-Key`               | mutation 必填 | `POST/PATCH/DELETE`    | 防重复提交，建议格式 `role-project-action-timestamp-random` |
| `If-Match`                      | 条件必填      | 更新、删除、提交、归档 | 对象版本号或 ETag；冲突返回 `ETAG_CONFLICT`                 |
| `Content-Type`                  | mutation 必填 | `POST/PATCH/DELETE`    | JSON 为 `application/json`，上传直传按签名 URL 要求         |

所有详情、列表行和 mutation 输出对象必须带版本字段：

```ts
type VersionedEntity = {
  id: string;
  revision: number;
  etag: string;
  updatedAt: string;
};
```

前端提交 `PATCH/DELETE/提交/归档/发布/回滚` 时传 `If-Match: <etag>`。mock 若收到过期 ETag，返回：

```json
{
  "code": 40904,
  "message": "对象已被其他用户更新，请刷新后重试。",
  "data": {
    "reason": "ETAG_CONFLICT",
    "currentEtag": "W/\"node-24-r8\"",
    "submittedEtag": "W/\"node-24-r7\""
  },
  "operationId": "MOCK-409",
  "serverTime": "2026-06-26 10:30:00"
}
```

### 23.2 字段级通用校验

| 字段                | 规则                                                              | 错误码                  |
| ------------------- | ----------------------------------------------------------------- | ----------------------- |
| `projectId`         | 必须匹配 `^P-[0-9]{4}-[A-Z0-9-]{3,32}$`                           | `VALIDATION_ERROR`      |
| `nodeId`            | 整数，范围 `1..69`                                                | `VALIDATION_ERROR`      |
| `documentId`        | 必须匹配 `^DOC-[A-Za-z0-9-]{6,64}$`                               | `VALIDATION_ERROR`      |
| `documentVersionId` | 必须匹配 `^DV-[A-Za-z0-9-]{6,80}$`                                | `VALIDATION_ERROR`      |
| `bindingId`         | 必须匹配 `^BIND-[A-Za-z0-9-]{6,64}$`                              | `VALIDATION_ERROR`      |
| `submissionId`      | 必须匹配 `^SUB-[A-Za-z0-9-]{6,64}$`                               | `VALIDATION_ERROR`      |
| `rectificationId`   | 必须匹配 `^REC-[A-Za-z0-9-]{6,64}$` 或 `^RCN-[A-Za-z0-9-]{6,64}$` | `VALIDATION_ERROR`      |
| `opinion`           | 必填，`5..2000` 字                                                | `VALIDATION_ERROR`      |
| `reason`            | 关键动作必填，`2..500` 字                                         | `VALIDATION_ERROR`      |
| `deadline`          | 必须晚于当前时间，格式 `YYYY-MM-DD HH:mm:ss`                      | `VALIDATION_ERROR`      |
| `page`              | 整数，`1..10000`                                                  | `VALIDATION_ERROR`      |
| `pageSize`          | 整数，`1..200`；默认 `20`                                         | `VALIDATION_ERROR`      |
| `sortOrder`         | 只能是 `asc/desc`                                                 | `VALIDATION_ERROR`      |
| `keyword`           | 最长 `100` 字，前后 trim                                          | `VALIDATION_ERROR`      |
| `fileName`          | `1..180` 字，不允许路径分隔符                                     | `VALIDATION_ERROR`      |
| `fileSize`          | `1B..500MB`；归档包可到 `2GB`                                     | `FILE_TOO_LARGE`        |
| `fileType`          | 允许 `pdf/doc/docx/xls/xlsx/png/jpg/jpeg/zip/7z` 对应 MIME        | `UNSUPPORTED_FILE_TYPE` |
| `hash`              | 推荐 SHA-256，64 位十六进制                                       | `VALIDATION_ERROR`      |
| `confidence`        | 数字，`0..1`                                                      | `VALIDATION_ERROR`      |

### 23.3 Mutation 必填字段矩阵

| 动作                                       | 必填字段                                                           | 条件必填                                             | 最小成功返回                                                 |
| ------------------------------------------ | ------------------------------------------------------------------ | ---------------------------------------------------- | ------------------------------------------------------------ |
| 新建项目 `POST /api/projects`              | `code/name/type/region/ownerOrgId/plannedStartDate/plannedEndDate` | `contractorOrgId/inspectionOrgId` 在初始化流程前必填 | `{ project: Project }`                                       |
| 更新项目 `PATCH /api/projects/{projectId}` | `If-Match`                                                         | 至少 1 个可编辑字段                                  | `{ project: Project }`                                       |
| 绑定参建单位                               | `unitType/unitName/contactName/contactPhone`                       | `licenseNo` 对施工、无损检测、监检机构必填           | `{ participant: ProjectUnit }`                               |
| 项目成员授权                               | `userId/role/nodeScope/actions`                                    | `expiresAt` 可选                                     | `{ memberId, actions, nodeScope }`                           |
| 初始化流程                                 | `templateVersion/stateMachineVersion/todoRuleVersion`              | 项目参建单位必须齐全                                 | `{ workflowId, nodeCount: 69, nextStatus }`                  |
| 创建上传会话                               | `files[].fileName/files[].fileSize/files[].fileType/sourceOrgId`   | `defaultNodeIds` 可空                                | `{ uploadSessionId, uploadUrls[] }`                          |
| 上传完成                                   | `completedFiles[].documentVersionId/hash/fileSize`                 | 分片上传需 `partEtags[]`                             | `{ documents[], versions[], ocrTaskIds[] }`                  |
| 新版本                                     | `uploadSessionId/replaceCurrent`                                   | `remark` 在替换当前版本时必填                        | `{ document, newVersion, previousVersionId }`                |
| 保存挂载                                   | `bindings[].documentVersionId/nodeId/usage`                        | `requirementId` 对必传资料项必填                     | `{ bindings[], packageSummary }`                             |
| 提交历史                                   | `projectId`                                                        | 无                                                   | `{ drafts[], submissions[] }`，已撤回批次必须含 `withdrawal` |
| 提交批次                                   | `bindingIds/nodeIds`                                               | `draftId` 可选                                       | `{ submissionId, snapshotId, nextStatus, createdTodos[] }`   |
| 撤回未提交项                               | `reason`                                                           | `bindingIds` 或 `documentVersionIds` 至少一个        | `MockMutationResult`；提交详情和历史需可追溯撤回原因         |
| 提交补正                                   | `nodeId/description`                                               | `bindingIds/files/evidenceLinkIds` 至少一个          | `{ rectification, nextStatus }`                              |
| 监检上传附件                               | `files[].fileName/type`                                            | `bindToRequirementId` 可选                           | `{ documents[], bindings[], evidenceLinks[] }`               |
| AI 重新核验                                | `reason`                                                           | `force=true` 时必须 `reason`                         | `{ runId, status, latestRun }`                               |
| 保存审查意见                               | `result/opinion/evidenceLinkIds`                                   | `riskLevel` 在 `result=需补正` 时必填                | `{ opinion, nextStatus }`                                    |
| 采纳 AI 建议                               | `result/opinion/reason`                                            | 无                                                   | `{ draftOpinion, auditLogId }`                               |
| 驳回 AI 建议                               | `reason`                                                           | `manualOpinion` 可选                                 | `MockMutationResult`                                         |
| 退回补正                                   | `responsibleOrgId/deadline/requirement`                            | `bindingIds` 或 `evidenceLinkIds` 至少一个           | `{ rectification, nextStatus, createdTodos[], messages[] }`  |
| 报告生成/复核                              | `includeEvidence/reportScope`                                      | 项目范围报告需全部关键节点通过或确认例外             | `{ report, nextStatus }`                                     |
| 报告导出                                   | `format`                                                           | `format=pdf` 可带 `watermark`                        | `{ exportId, report }`                                       |
| 报告归档                                   | `archiveNote`                                                      | `If-Match` 必填                                      | `{ report, nextStatus: '已归档' }`                           |
| 规则发布                                   | `reason`                                                           | `effectiveAt` 可选                                   | `MockMutationResult`                                         |
| 规则回滚                                   | `reason/targetVersion`                                             | 无                                                   | `MockMutationResult`                                         |
| 知识源启停                                 | `reason`                                                           | 无                                                   | `{ source }`                                                 |
| 任务重试/取消                              | `reason`                                                           | 取消运行中任务需 `force=true`                        | `{ task }`                                                   |

提交批次弹窗的三个 mutation（保存草稿、提交批次、撤回未提交项）在返回非 0 业务错误时，前端必须保留当前弹窗、表单输入、已选资料和节点范围；错误信息需就近展示在弹窗内，并提供按当前表单内容重试的入口。`ETAG_CONFLICT`、`EMPTY_NODE_PACKAGE`、`WITHDRAW_LOCKED` 是该弹窗的最低错误恢复验收样例。

资料挂载弹窗在 `POST /api/projects/{projectId}/documents/bindings` 返回非 0 业务错误时，前端必须保留当前项目资料、版本、用途和目标节点选择；错误信息需就近展示在弹窗内，并提供按当前选择重试挂载的入口。`ETAG_CONFLICT`、`EMPTY_BINDINGS`、`DOCUMENT_NOT_FOUND` 是该弹窗的最低错误恢复验收样例。

无损检测工作流的 `POST /api/projects/{projectId}/ndt/films` 在返回非 0 业务错误时，前端必须保留当前底片编号、焊口编号、检测方法、管线号和检测日期；错误信息需就近展示在 NDT 底片表单内，并提供按当前表单重试的入口。`TASK_RUNNING`、`ETAG_CONFLICT`、`NDT_FILM_REQUIRED` 是该操作的最低错误恢复验收样例。

无损检测工作流的 `POST /api/projects/{projectId}/ndt/records/import` 在返回非 0 业务错误时，前端必须保留当前导入行和记录表单字段；错误信息需就近展示在 NDT 记录导入表单内，并提供按当前表单重试的入口。`TASK_RUNNING`、`ETAG_CONFLICT`、`NDT_RECORD_REQUIRED` 是该操作的最低错误恢复验收样例。

无损检测工作流的 `POST /api/projects/{projectId}/ndt/submissions` 在返回非 0 业务错误时，前端必须保留当前待提交报告、底片和节点上下文；错误信息需就近展示在 NDT 操作区，并提供按当前待提交集合重试的入口。`TASK_RUNNING`、`ETAG_CONFLICT`、`NDT_REPORT_REQUIRED` 是该操作的最低错误恢复验收样例。

无损检测工作流的 `POST /api/projects/{projectId}/ndt/rectifications` 在返回非 0 业务错误时，前端必须保留当前反馈事项、补正说明、报告和底片上下文；错误信息需就近展示在 NDT 补正表单内，并提供按当前表单重试的入口。`TASK_RUNNING`、`ETAG_CONFLICT`、`NDT_RECTIFICATION_REQUIRED` 是该操作的最低错误恢复验收样例。

只读和导出链路的 `GET /api/projects/{projectId}/reports/{reportId}`、`GET /api/projects/{projectId}/archive/{archiveItemId}`、`GET /api/projects/{projectId}/export-tasks/{exportId}` 在返回非 0 业务错误时，前端必须保留当前详情抽屉、最近请求 ID 和列表上下文；错误信息需就近展示在抽屉内，并提供按当前 ID 重试加载的入口。`REPORT_NOT_FOUND`、`ARCHIVE_NOT_FOUND`、`EXPORT_TASK_NOT_FOUND` 是该链路的最低错误恢复验收样例。

### 23.4 状态机和合法流转

状态流转必须由后端和 mock 同时约束。前端不能只靠按钮显隐判断是否允许动作。

| 对象          | 当前状态          | 允许动作          | 下一个状态                   | 禁止动作示例     |
| ------------- | ----------------- | ----------------- | ---------------------------- | ---------------- |
| Project       | `草稿/立项中`     | 初始化流程        | `资料提交中`                 | 报告归档         |
| Project       | `资料提交中`      | 提交批次          | `AI 预审中` 或 `监检审查中`  | 删除项目         |
| Project       | `AI 预审中`       | AI 完成           | `监检审查中` 或 `退回补正中` | 报告归档         |
| Project       | `监检审查中`      | 保存全部关键意见  | `报告生成/复核中`            | 修改流程模板     |
| Project       | `退回补正中`      | 提交补正          | `监检审查中`                 | 报告归档         |
| Project       | `报告生成/复核中` | 报告确认归档      | `已归档`                     | 上传施工资料     |
| Project       | `已归档`          | 查看/下载/导出    | `已归档`                     | 任意 mutation    |
| Node          | `待提交`          | 提交文件          | `AI 预审中` 或 `待审查`      | 保存审查意见     |
| Node          | `AI 预审中`       | AI 完成           | `待人工确认` 或 `待审查`     | 重复提交同一批次 |
| Node          | `待人工确认`      | 保存意见/退回补正 | `已通过` 或 `需补正`         | 自动通过         |
| Node          | `需补正`          | 施工方反馈        | `复审中`                     | 报告生成         |
| Node          | `复审中`          | 复审通过/再次退回 | `已通过` 或 `需补正`         | 删除证据链       |
| File          | `草稿`            | 上传完成/撤回     | `已上传` 或 `已撤回`         | 审查通过         |
| File          | `已上传`          | 挂载/提交/替换    | `已上传` 或 `已替换`         | 物理删除         |
| Binding       | `草稿挂载`        | 提交/解除         | `已提交` 或 `已解除挂载`     | 审查通过         |
| Binding       | `已提交`          | 审查/退回         | `已通过` 或 `需补正`         | 解除挂载         |
| Rectification | `待补正`          | 提交反馈          | `已反馈` 或 `复审中`         | 关闭任务         |
| AiReviewRun   | `推理中`          | 完成/失败         | `完成` 或 `失败`             | 再次启动同一 run |
| KnowledgeTask | `排队中`          | 取消/运行         | `已取消` 或 `运行中`         | 重试             |
| KnowledgeTask | `失败`            | 重试              | `排队中`                     | 取消             |
| Report        | `草稿`            | 保存/提交复核     | `复核中`                     | 归档             |
| Report        | `复核中`          | 确认/退回         | `已确认` 或 `草稿`           | 删除项目资料     |
| Report        | `已确认`          | 导出/归档         | `已导出` 或 `已归档`         | 修改审查意见     |

状态冲突统一返回：

```ts
type ConflictDetail = {
  objectType: string;
  objectId: string;
  currentStatus: string;
  attemptedAction: string;
  allowedActions: ActionCode[];
  refreshEndpoint: string;
};
```

### 23.5 页面级 mock 种子数据

前端 mock 建议从一个固定 seed 派生所有列表和详情，避免同一项目、节点、文件在不同页面显示不一致。

```ts
type MockSeed = {
  users: User[];
  projects: Project[];
  treeGroups: Array<{ name: string; nodes: ProjectTreeNode[] }>;
  requirements: NodeDocumentRequirement[];
  documents: DocumentAsset[];
  versions: DocumentVersion[];
  bindings: NodeFileBinding[];
  extractedFields: ExtractedField[];
  evidenceLinks: EvidenceLink[];
  aiRuns: AiReviewRun[];
  opinions: ReviewOpinion[];
  rectifications: RectificationPayload[];
  todos: TodoItem[];
  messages: MessageItem[];
  reports: ReportVersion[];
  auditLogs: AuditLog[];
};
```

最小 seed 必须包含：

| 类别       |    数量 | 必须覆盖的状态                                    |
| ---------- | ------: | ------------------------------------------------- |
| 项目       |       4 | `监检审查中`、`退回补正中`、`AI 预审中`、`已归档` |
| 树节点     |      69 | A/B/C/C-B/需确认节点类型                          |
| 资料项要求 | 至少 20 | 必传、条件必传、可选                              |
| 文件       | 至少 12 | 草稿、已上传、已撤回、已替换、已作废              |
| 挂载       | 至少 16 | 草稿挂载、已提交、需补正、已通过                  |
| OCR 字段   | 至少 20 | 高置信度、低置信度、人工修正                      |
| 证据链     | 至少 20 | OCR 区域、标准条款、AI run、人工意见              |
| AI run     |  至少 4 | 完成、失败、推理中、已人工确认                    |
| 审查意见   |  至少 6 | 满足要求、需补正、不适用                          |
| 补正任务   |  至少 4 | 待补正、已反馈、复审中、已关闭                    |
| 待办       |  至少 8 | 不同角色、不同优先级、超期                        |
| 消息       |  至少 8 | 已读、未读、项目消息、系统消息                    |
| 报告       |  至少 4 | 草稿、复核中、已导出、已归档                      |

推荐前端本地 mock 文件结构：

```text
src/mock/
  seed/
    projects.ts
    tree.ts
    documents.ts
    inspection.ts
    ndt.ts
    knowledge.ts
    admin.ts
  handlers/
    workbench.ts
    documents.ts
    submissions.ts
    inspection.ts
    knowledge.ts
    admin.ts
  state.ts
  errors.ts
  index.ts
```

### 23.6 Mock handler 必须模拟的状态写入

| Handler                   | 写入对象                                        | 必须同步更新                                           |
| ------------------------- | ----------------------------------------------- | ------------------------------------------------------ |
| `createUploadSession`     | `documents/versions`                            | `ocrTasks`、项目文件库计数；失败时不写状态             |
| `completeUploadSession`   | `versions`                                      | 文件状态、OCR 状态、知识库项目文件任务                 |
| `bindDocumentsToNodes`    | `bindings`                                      | 节点 `fileCount/requiredProgress`                      |
| `submitContractorBatch`   | `submissions/bindings/nodes/todos/messages`     | 绑定状态、节点状态、监检待办                           |
| `withdrawSubmissionItems` | `bindings/submissions/nodes/messages/auditLogs` | 绑定回草稿挂载、提交快照写入撤回追溯、节点回到部分提交 |
| `submitRectification`     | `rectifications/bindings/nodes/todos/messages`  | 补正状态、复审待办                                     |
| `recheckNode`             | `aiRuns/evidenceLinks/todos`                    | AI 状态、人工确认待办                                  |
| `saveInspectionOpinion`   | `opinions/nodes/bindings/auditLogs`             | 节点状态、审查历史                                     |
| `returnCorrection`        | `rectifications/nodes/bindings/todos/messages`  | 责任单位待办、补正消息                                 |
| `startReportReview`       | `reports/todos/auditLogs`                       | 报告队列、复核待办                                     |
| `archiveReport`           | `reports/projects/archive/auditLogs`            | 项目只读、归档包                                       |
| `retryKnowledgeTask`      | `knowledgeTasks`                                | 任务状态、知识库总览指标                               |
| `publishRuleVersion`      | `rules/auditLogs`                               | 当前规则版本、节点规则引用                             |

### 23.7 文件上传和预览协议

文件上传采用“两段式会话”：

1. `POST /api/projects/{projectId}/documents/upload-session` 返回签名 URL、`documentId`、`documentVersionId`。
2. 真实后端返回 MinIO signed PUT，前端直接上传对象；mock-first 模式可以返回 `mock://upload/...` 并跳过真实对象上传。
3. `complete` 后必须创建 `DocumentAsset`、`DocumentVersion`、OCR 任务和知识库项目文件记录。

当前 `frontend/` 的 mock-first 页面允许 `upload-session` 在创建会话时直接写入项目资料池，以便不接真实对象存储也能完成上传、挂载和提交闭环；切换真实后端时保持返回结构不变，把状态写入下沉到 `complete` 即可。创建会话返回业务错误时，前端上传抽屉按第 22.11 节保留文件列表和重试入口。

真实后端的 `GET /api/projects/{projectId}/documents/{documentId}/preview-url` 和 `download-url` 必须基于当前 `DocumentVersion.storageBucket/storageKey` 生成短期 signed GET；URL 过期后前端重新请求即可。生产验收使用 `verify_deployment.py --write-probes --strict-production` 实际 PUT 一个 PDF，再 GET 新文档的 preview/download signed URL，证明上传对象、预览地址和下载地址指向同一对象存储链路。URL 中的 `projectId` 与文档归属不一致时返回 `NOT_FOUND`，不能泄露跨项目 signed URL。

`upload-session` 返回示例：

```json
{
  "code": 0,
  "data": {
    "uploadSessionId": "UP-20260626-001",
    "expiresAt": "2026-06-26 11:00:00",
    "uploadUrls": [
      {
        "fileName": "焊工资格证-王建国.pdf",
        "documentId": "DOC-20260626-001",
        "documentVersionId": "DV-20260626-001-V1",
        "url": "mock://upload/UP-20260626-001/1",
        "method": "PUT",
        "expiresAt": "2026-06-26 11:00:00",
        "headers": { "Content-Type": "application/pdf" }
      }
    ]
  },
  "operationId": "MOCK-10001",
  "serverTime": "2026-06-26 10:30:00"
}
```

### 23.8 权限矩阵补齐

| 角色         | 读                                     | 写                                                | 禁止                             |
| ------------ | -------------------------------------- | ------------------------------------------------- | -------------------------------- |
| `inspection` | 项目、节点、文件、证据、AI、报告       | 监检上传、挂载、审查意见、退回补正、报告生成/复核 | 施工方草稿编辑、后台配置发布     |
| `contractor` | 授权项目、反馈、本人单位文件、节点要求 | 上传、挂载、草稿、提交、补正反馈、撤回未提交项    | 审查意见、AI 建议采纳、报告归档  |
| `ndt`        | 授权项目、无损检测节点、监检反馈       | 底片、检测记录、检测报告、检测资料提交、补正反馈  | 材料节点施工方资料编辑、报告归档 |
| `owner`      | 项目概况、节点摘要、报告预览、归档资料 | 无业务写入；只允许消息已读、导出只读资料          | 上传、提交、审查、补正、配置     |
| `admin`      | 全局配置、审计、知识库、规则           | 配置、规则、知识任务、用户角色、流程模板          | 代替业务人员出具审查意见         |

mock 中任何角色调用禁止动作，都返回 `FORBIDDEN`，并在 `data.reason` 和附加字段中包含：

```ts
type ForbiddenDetail = {
  role: RoleCode;
  action: string;
  requiredActions: ActionCode[];
  readonly: boolean;
  readonlyReason?: string;
};
```

### 23.9 OpenAPI 拆分建议

进入真实后端联调前，建议将本文档拆为以下 OpenAPI 文件：

| 文件                                  | 内容                                                                        |
| ------------------------------------- | --------------------------------------------------------------------------- |
| `openapi/common.yaml`                 | `ApiResult/Page/Error/headers/securitySchemes`                              |
| `openapi/schemas-project.yaml`        | `Project/ProjectUnit/User/ProjectTreeNode/Workflow`                         |
| `openapi/schemas-document.yaml`       | `DocumentAsset/DocumentVersion/NodeFileBinding/ExtractedField/EvidenceLink` |
| `openapi/schemas-review.yaml`         | `AiReviewRun/ReviewOpinion/Rectification/Report/AuditLog`                   |
| `openapi/paths-workbench.yaml`        | 权限、项目、工作台、树、节点包                                              |
| `openapi/paths-documents.yaml`        | 文件库、上传、预览、挂载                                                    |
| `openapi/paths-submissions.yaml`      | 草稿、提交、撤回、补正                                                      |
| `openapi/paths-inspection.yaml`       | AI、审查、证据、退回补正、报告复核                                          |
| `openapi/paths-ndt-owner-report.yaml` | 无损检测、建设方、报告、归档                                                |
| `openapi/paths-knowledge-admin.yaml`  | 知识库、规则、后台配置、审计                                                |

每个 OpenAPI path 必须包含：

- `operationId`，命名格式 `domain_action_object`，例如 `documents_createUploadSession`。
- `security`，引用 bearer token。
- `parameters`，包含 path/query/header。
- `requestBody.required` 和字段级校验。
- `responses.200`、`400`、`401`、`403`、`404`、`409`。
- 至少 1 个成功 example 和 1 个错误 example。
- mutation 必须声明 `Idempotency-Key`，更新/删除必须声明 `If-Match`。

### 23.10 补齐后验收清单

前端 mock 开发开始前，按以下清单验收：

| 检查项   | 必须通过                                             |
| -------- | ---------------------------------------------------- |
| 路径覆盖 | `ui`、设计文档中出现的 `/api/...` 均能在本文档找到   |
| 页面覆盖 | 静态 section、知识库页面、导航映射均能在第 19 节找到 |
| 参数覆盖 | 每个前端调用都有 path/query/body 描述                |
| 输出覆盖 | 每个页面首屏接口都有可渲染的 `data` 类型             |
| 状态覆盖 | 所有 mutation 都有状态变化或明确“无状态变化”         |
| 权限覆盖 | 每个写动作都能按角色模拟允许/禁止                    |
| 错误覆盖 | 至少能 mock 第 22.11 节 8 类错误                     |
| 幂等覆盖 | 重复提交同一 `Idempotency-Key` 返回同一结果          |
| 并发覆盖 | 过期 `If-Match` 返回 `ETAG_CONFLICT`                |
| 文件覆盖 | 上传、完成、预览、下载、OCR 均可 mock                |
| 证据覆盖 | AI、OCR、标准条款、人工意见都能回到 `EvidenceLink`   |
| 审计覆盖 | mutation 都能生成 `auditLogId`                       |
| 联调清单 | 字段差异可按模块/状态筛选，并能标记阻塞项            |

### 23.11 联调字段差异清单

`GET /api/admin/integration-contract` 是真实后端联调对账接口，前端用于在管理后台集中展示 mock 合同和真实后端字段之间的差异。当前真实后端样例覆盖 `workbench/documents/submissions/inspection/ndt-owner-report/knowledge-admin` 六个模块，基线为 `summary.blockers = 0`、`summary.pending = 0`、`summary.aligned = summary.total`；接口仍必须支持 `module/status` 筛选，以便后续出现字段差异时定位责任域。

实现要求：

- `summary.total/aligned/pending/blockers` 必须基于当前筛选结果计算。
- `modules` 必须返回所有模块，筛选后无字段的模块 `total` 为 `0`，便于前端保持固定布局。
- `fields[].endpoint/method/frontendField/backendField/required/status/severity/owner/note` 必须完整返回；`backendField` 缺失时返回空字符串。
- `severity=danger` 视为联调阻塞项，必须进入 `summary.blockers` 和模块 `blockers`。
- 该接口不写审计、不触发配置版本变化，只作为 mock 开发和真实联调前的合同看板。

补齐到第 23 节后，文档已经足够支撑两阶段工作：

1. 前端 mock 开发：直接按第 22、23 节实现 mock state、handlers 和错误态。
2. 后端联调准备：将第 4、22、23 节结构化为 OpenAPI 3.1，再做 SDK/codegen。
