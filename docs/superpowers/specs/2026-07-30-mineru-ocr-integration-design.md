# MinerU OCR 精准解析接入设计

## 背景

项目同时保留本地 OCR 服务和 MinerU 远程 OCR。统一 OCR 流程通过
`AICHECK_OCR_DEFAULT_PROVIDER` 选择缺省 Provider，允许值为 `local` 或 `mineru`，
部署缺省值为 `mineru`。

独立 MinerU 接口始终调用 MinerU。现有统一 OCR 请求显式传入
`options.provider` 时覆盖缺省配置；未显式传入时使用
`AICHECK_OCR_DEFAULT_PROVIDER`。

参考文档：

- <https://mineru.net/apiManage/docs>
- <https://opendatalab.github.io/MinerU/reference/output_files/>

## 目标

1. 接入 MinerU 精准解析 API，模型固定为 `vlm`。
2. 提供独立异步 OCR 接口，支持公网 URL、项目 `storageKey` 和直接上传文件。
3. 允许现有 OCR 流程通过配置或 `options.provider` 在本地 OCR 与 MinerU 之间选择，默认 MinerU。
4. 解析 MinerU 返回的新旧 Zip 布局、Markdown 和结构化 JSON。
5. 将结果转换为现有 OCR 证据契约并写入 `ocr_jobs`、`ocr_parse_results` 和 `ocr-artifacts`。
6. 请求绑定业务文档版本时，通过现有 `apply_ocr_result()` 更新本地字段、表格、证据和文档 OCR 状态。
7. 将 MinerU 密钥保存在 `backend/.env`，不写入 Git、日志、响应或持久化任务参数。

## 非目标

- 不把 MinerU 加入本地 OCR 服务的自动失败回退。
- 不把远程调用放入当前 `offline-only` 的本地 OCR 容器。
- 不支持调用方切换 MinerU 模型版本。
- 不实现 MinerU callback；首版使用现有远程 Worker 轮询。
- 不根据 MinerU 结果自动作出业务合规结论。

## 方案选择

采用独立远程适配层：

- API 服务负责验证请求、创建本地 OCR Job 和返回状态。
- `ocr.remote` Worker 负责 MinerU 提交、上传、轮询、下载和结果归一化。
- 共享集成客户端只处理 MinerU HTTP 协议。
- 独立归一化模块只处理 MinerU 产物到本地 OCR 契约的转换。
- 当前本地 OCR 微服务继续保持离线，不接收 MinerU 密钥。

没有采用以下方案：

- 直接集成本地 OCR 微服务：会破坏现有离线边界。
- 仅代理 MinerU 原始响应：无法接入本地 OCR 存储和证据链。
- 改造现有阿里云千问客户端：两个上游协议和结果结构不同，强行复用会导致职责混乱。

## 组件边界

### MinerU HTTP 客户端

建议位置：`backend/libs/integrations/mineru_client.py`

职责：

- 从 `AICHECK_MINERU_API_KEY` 读取 Token。
- 使用 `Authorization: Bearer <token>` 调用 MinerU。
- URL 输入调用 `POST /api/v4/extract/task`。
- 本地文件输入调用 `POST /api/v4/file-urls/batch`，随后 PUT 文件到 MinerU 返回的上传地址。
- 单任务调用 `GET /api/v4/extract/task/{task_id}`。
- 上传任务调用 `GET /api/v4/extract-results/batch/{batch_id}`。
- 将 HTTP 错误、MinerU 业务错误码和任务状态转换为类型化异常或统一结果。
- 对瞬时错误执行有界重试，但不记录 Token、授权头或签名上传 URL。

客户端不负责数据库、业务 Job、Zip 解压或本地 OCR 结构转换。

### MinerU 结果归一化器

建议位置：`backend/libs/mineru_ocr.py`

职责：

- 安全下载并解压 `full_zip_url`。
- 定位 `full.md`、`*_content_list.json`、页面布局 JSON 和相关图片。
- 页面布局优先使用旧格式 `*_middle.json`；缺失时使用当前 VLM 格式的
  `layout.json`。两者都缺失时返回 `MINERU_PAGE_LAYOUT_MISSING`。
- 将 MinerU 页、内容块、表格、公式和印章候选转换为现有 OCR 结构。
- 生成质量标记、诊断信息、引擎执行记录和 Provider 元数据。
- 返回可直接交给 `finish_ocr_job_record()` 的结果。

归一化器不负责提交任务、轮询或写数据库。

### API 路由

建议使用独立路由模块，避免继续扩大 `backend/apps/api/routes.py`：

`backend/apps/api/mineru_ocr_routes.py`

接口：

#### `POST /internal/ocr/mineru/tasks`

JSON 请求支持以下二选一输入：

```json
{
  "url": "https://example.com/document.pdf",
  "fileName": "document.pdf",
  "documentId": "DOC-001",
  "documentVersionId": "VER-001",
  "profileId": "generic_document_v1",
  "documentType": "generic_document",
  "options": {
    "language": "ch",
    "pageRanges": "1-20",
    "noCache": false
  }
}
```

或：

```json
{
  "storageKey": "minio://documents/path/document.pdf",
  "fileName": "document.pdf",
  "documentId": "DOC-001",
  "documentVersionId": "VER-001",
  "profileId": "generic_document_v1",
  "documentType": "generic_document",
  "options": {}
}
```

约束：

- `url` 和 `storageKey` 必须且只能提供一个。
- `model_version` 不接受客户端输入，服务端始终发送 `vlm`。
- 服务端始终发送 `is_ocr=true`、`enable_formula=true`、`enable_table=true`。
- 只有 `storageKey` 可绑定 `documentId` 和 `documentVersionId`，且必须与该版本的对象键完全一致；公网 URL 和原始上传始终作为独立任务，不能覆盖业务文档。
- POST 请求支持 `Idempotency-Key`，相同授权上下文、请求指纹和幂等键不会重复存储或派发。

成功响应立即返回本地 `jobId`、`status=queued` 和轮询地址，不等待 MinerU 完成。

#### `POST /internal/ocr/mineru/tasks/upload`

沿用现有 OCR 上传接口的原始字节流方式：

- 请求体是文件字节。
- `X-AICheck-Ocr-Metadata-B64` 携带 Base64URL 编码的 JSON 元数据。
- 元数据包括 `fileName`、Profile 和选项，不接受业务文档绑定。
- API 先完整校验元数据，再把原文件写入受控对象存储并创建远程 Job。
- 不在 Job 参数中保存临时本地路径。

#### `GET /internal/ocr/mineru/tasks/{job_id}`

返回：

- 本地状态：`queued`、`running`、`success`、`failed` 或 `canceled`。
- 当前阶段：`submit`、`upload`、`poll`、`download`、`normalize`、`persist`。
- MinerU 进度：已解析页数和总页数。
- 成功时返回 `parseResultId`、结果摘要和产物引用。
- 失败时返回本地 `diagnostics`，不返回敏感上游请求数据。

### Provider 路由

现有 OCR 流程按以下优先级选择 Provider：

```python
options.get("provider") or AICHECK_OCR_DEFAULT_PROVIDER
```

只接受 `local` 或 `mineru`。显式 `options.provider` 优先；未指定或空值时读取
`AICHECK_OCR_DEFAULT_PROVIDER`，该变量未设置时使用 `mineru`。非法显式值或非法配置值
均以 `OCR_PROVIDER_UNSUPPORTED` 失败，不静默回落。路由发生在 Worker 调度层，不发生在
本地 OCR 微服务内部。

统一文档上传接口在每个 `files[]` 条目中接受
`ocrOptions.provider="local"|"mineru"`，验证后持久化到对应文档版本。所有统一 OCR
准备任务固定进入 Provider 中立的 `ocr.parse_document` 队列；该无密钥 Worker 解析
Provider 后，只有 MinerU 分支继续派发到 `ocr.remote`。

MinerU 请求沿用现有 OCR Pipeline 的业务标识和持久化流程，因此业务调用方不需要消费另一套结果结构。

## 数据流

### URL 输入

1. API 验证 HTTPS 公网 URL、后缀和请求字段。
2. 创建 `ocr_jobs` 记录并派发 `ocr.remote` 任务。
3. Worker 调用 MinerU 单文件任务接口，模型为 `vlm`。
4. Worker 轮询单任务结果，持续更新本地 Job 阶段和进度。
5. 完成后下载结果 Zip，归一化并持久化。

### storageKey 输入

1. API 验证 `storageKey` 和文件名。
2. 创建 `ocr_jobs` 记录并派发 `ocr.remote` 任务。
3. Worker 从对象存储下载文件到受控临时目录。
4. Worker 申请 MinerU 上传地址并上传文件。
5. Worker 轮询批量任务结果，持续更新本地 Job。
6. 完成后下载结果 Zip，归一化并持久化。
7. 临时文件在成功或失败后删除。

### 上传输入

1. API 验证文件名、扩展名和字节数。
2. API 将原文件写入项目对象存储并取得 `storageKey`。
3. 后续流程与 `storageKey` 输入一致。

## MinerU 返回解析

### 产物发现

Zip 内文件名前缀不作为固定常量。归一化器按后缀发现：

- 唯一的 `*_content_list.json`
- 优先选择唯一的 `*_middle.json`；不存在时选择唯一且 basename 为
  `layout.json` 的当前 VLM 页面布局
- `full.md`，或唯一的 `.md` 主文件

缺少 `content_list`、两种页面布局都缺失或内容不可解析时任务失败。缺少 Markdown 时
仍可基于结构化 JSON 成功，但添加诊断信息。

### 页映射

MinerU `page_idx` 从 0 开始，本地 `pageNo` 从 1 开始：

```text
pageNo = page_idx + 1
```

从 `middle.json` 获取每页 `page_size=[width,height]`，生成本地 `pages`：

```json
{
  "pageNo": 1,
  "width": 1190,
  "height": 1684,
  "coordinateSystem": "rendered_pixels",
  "sourceCoordinateSystem": "mineru_normalized_1000"
}
```

### 坐标映射

MinerU `content_list.json` 的 `bbox=[x0,y0,x1,y1]` 映射到 0–1000。转换公式：

```text
local_x = mineru_x / 1000 * page_width
local_y = mineru_y / 1000 * page_height
```

所有成功转换的证据项包含：

- `coordinateSystem="rendered_pixels"`
- `sourceCoordinateSystem="mineru_normalized_1000"`
- `coordinateTransformStatus="mapped"`
- 原始坐标和转换参数

页尺寸缺失、坐标越界或坐标格式错误时，不伪造位置；项目增加 `coordinate_transform_unmapped` 质量标记，该项不能满足正式证据完整性。

### fragments 和 layoutBlocks

以下 MinerU 内容类型转换成 `fragments`：

- `text`、标题和页辅助文本：使用 `text`
- `equation`：使用公式 `text`
- `list`：按 `list_items` 顺序合并并保留内容类型
- `code`：使用 `code_body`
- 图片和图表：使用说明、脚注或结构化 `content`

每个 fragment 至少包含：

- 稳定的 `fragmentId`
- `pageNo`
- `text`
- `bbox`（可映射时）
- `sourceEngine="mineru_vlm"`
- 内容类型和阅读顺序

相同内容块也写入 `layoutBlocks`，用于版面和 EvidenceRef 定位。

### tables

MinerU `table_body` HTML 复用本地 `html_table_to_structure()`，生成：

- `rows`
- `columns`
- `cells`
- `normalizedRows`

表格同时保留：

- 页码和表格 bbox
- caption 和 footnote
- 原始 HTML 的 artifact 引用
- `sourceEngine="mineru_vlm"`

HTML 为空或结构无法解析时保留表格候选和诊断，不生成虚假单元格。

### seals

MinerU 的 `image` 且 `sub_type="seal"` 转为本地 `seals` 候选。

如果 MinerU 没有提供可验证的印章文字：

- `candidateOnly=true`
- `canSatisfyRequiredSeal=false`
- 添加 `requires_seal_ocr_text`

不得仅凭图片分类生成单位名称、证书编号或印章结论。

### fields

MinerU 不直接提供项目 Profile 字段。归一化完成后，复用现有 Profile enrichment，从 fragments、tables 和 seals 生成字段候选。字段必须保留页码、证据坐标和 `sourceEngine`。

### 置信度

MinerU VLM 结构化输出可能不给出可用分数。缺少 Provider 分数时：

- 不填充人为固定高分。
- `confidence` 使用本地契约允许的空值或零值。
- 添加 `provider_confidence_unavailable`。
- 下游质量判断可以要求人工复核。

## 本地持久化

### 任务记录

使用现有 `repo.create_ocr_job_record()` 创建 `ocr_jobs`。Job 附加非敏感字段：

- `provider="mineru"`
- `model="vlm"`
- `providerTaskType="task"` 或 `batch`
- MinerU `task_id` 或 `batch_id`
- 文件批次的 `providerUploadState="allocated"` 或 `uploaded`
- 阶段、进度和重试计数

不保存 Token、Authorization header 或签名上传 URL。

### 解析结果

标准化结果通过 `repo.finish_ocr_job_record()` 写入 `ocr_parse_results`，字段包括：

- `pages`
- `fragments`
- `layoutBlocks`
- `tables`
- `seals`
- `fields`
- `quality`
- `diagnostics`
- `engineRuns`
- `metadata`
- `groundingValidation`

`parserVersion` 使用独立版本，例如 `mineru-vlm-adapter@1`。

### 业务应用

请求同时绑定有效 `documentId` 和 `documentVersionId` 时，结果成功后调用现有：

```python
repo.apply_ocr_result(document_id, document_version_id, result_record)
```

没有业务文档绑定的独立请求只保存 Job 和 ParseResult，不创建虚假业务文档，也不修改文档状态。

### 原始产物

以下内容写入现有 `ocr-artifacts` 对象存储：

- 原始结果 Zip
- Markdown
- content list
- 实际使用的页面布局 JSON：旧格式保存为 `middle_json`，当前 VLM 格式保存为
  `layout_json`
- 标准化结果 JSON

数据库只保存对象引用、SHA-256、内容类型和字节数。对象名使用本地 Job ID，不使用外部 URL 中的路径。

## 配置

本地私密文件 `backend/.env`：

```dotenv
AICHECK_MINERU_API_KEY=<real-token>
AICHECK_OCR_DEFAULT_PROVIDER=mineru
```

版本控制中的 `backend/.env.example`：

```dotenv
AICHECK_MINERU_BASE_URL=https://mineru.net
AICHECK_MINERU_API_KEY=replace-with-mineru-api-key
AICHECK_MINERU_MODEL_VERSION=vlm
AICHECK_OCR_DEFAULT_PROVIDER=mineru
AICHECK_MINERU_TIMEOUT_SECONDS=60
AICHECK_MINERU_POLL_INTERVAL_SECONDS=3
AICHECK_MINERU_JOB_TIMEOUT_SECONDS=1800
```

`AICHECK_MINERU_MODEL_VERSION` 的部署值必须为 `vlm`；其他值在启动检查或请求前被拒绝。
`AICHECK_OCR_DEFAULT_PROVIDER` 只允许 `local` 或 `mineru`，未设置时为 `mineru`。

Docker Compose 把 Provider 选择变量传给负责统一 OCR 调度的 Worker；MinerU 密钥只传给
`ocr.remote` Worker，不传给 API 服务、本地 OCR Worker 或本地 OCR 容器。

## 验证和安全

### 请求验证

- URL 只接受 `https`。
- URL 主机解析结果不能是回环、私有、链路本地、组播或保留地址。
- URL、storageKey 和上传文件必须三选一。
- 文件名必须有受支持扩展名。
- 上传文件不得为空且不得超过 200MB。
- `data_id` 使用本地 Job ID 派生，只包含 MinerU 允许的字符且不超过 128 字符。
- `pageRanges` 必须满足 MinerU 页范围语法并限制到 200 页。

### 上游错误

错误分为：

- 不重试：Token 错误、Token 过期、参数错误、格式不支持、文件为空、超限、无权限。
- 可重试：网络超时、HTTP 429/5xx、服务异常、队列已满、模型暂时不可用。
- 终态失败：MinerU 任务 `state=failed`。

签名上传地址只保留在单次客户端调用的内存中，同一地址最多尝试三次。若文件批次在
`allocated` 状态中断，后续 Worker 先探测批次：`waiting-file` 时重新申请上传批次，
已经进入其他状态时继续原批次，避免把未上传的批次误当作可轮询任务。

所有错误转换为本地 `diagnostics`，包含稳定错误码、阶段和安全消息。

### 有界轮询

- 使用单调时钟控制总超时。
- 轮询间隔由配置决定，并有最小值。
- Worker 心跳更新本地 Job。
- 超时后本地 Job 失败；不把未知上游状态标记为成功。
- 首版取消只停止本地轮询，不承诺删除上游运行中任务。

### Zip 安全

- 下载设最大字节数和超时。
- 解压前验证成员数量、单成员大小和总解压大小。
- 拒绝绝对路径、`..`、符号链接和越界目标。
- 只解析预期文本和 JSON 产物。
- 临时目录在所有路径上清理。

### 秘密保护

- Token 只来自环境变量。
- 异常、日志、Job、响应和 artifact 不包含 Token。
- 不持久化 MinerU 签名上传 URL。
- 原始 URL 只在业务需要时保存；查询字符串默认脱敏。

## 测试策略

采用测试驱动开发。

### 客户端测试

- Bearer header 和固定 `vlm` 请求体。
- URL 单任务提交和查询。
- 文件上传地址申请、无 Content-Type PUT 和批量查询。
- MinerU 非零 code、HTTP 错误、无效 JSON和缺失字段。
- 可重试与不可重试错误分类。
- 日志和异常不泄露 Token 或签名 URL。

### 归一化测试

- `page_idx` 到 `pageNo`。
- 0–1000 bbox 到 `rendered_pixels`。
- 文本、标题、列表、公式、代码和图片说明。
- HTML 表格到本地 cells 和 normalizedRows。
- 印章候选不被误判为已验证印章。
- 缺置信度的质量标记。
- 缺文件、坏 JSON、Zip Slip、符号链接和解压炸弹。

### 路由测试

- 未指定 Provider 时使用配置值，配置未设置时调用 MinerU。
- `provider=local` 只调用现有本地 OCR。
- `provider=mineru` 只派发远程 MinerU 任务。
- 未知显式 Provider 或非法配置值返回验证错误，不静默回退。
- 独立 URL、storageKey 和上传接口都创建 MinerU Job。
- 多输入或无输入被拒绝。

### 持久化测试

- Job 阶段和进度持久化。
- 结果通过 `finish_ocr_job_record()` 写入 `ocr_parse_results`。
- 有业务文档绑定时调用 `apply_ocr_result()`。
- 无业务绑定时不创建或修改业务文档。
- 原始产物保存到 `ocr-artifacts` 且数据库只保留引用和哈希。

### 回归测试

- 现有 OCR contract 测试保持通过。
- 现有本地 OCR 路由和离线 readiness 保持不变。
- Compose 配置不把 MinerU 密钥传给本地 OCR 服务。

## 验收标准

1. `backend/.env` 存在 `AICHECK_MINERU_API_KEY`，文件仍被 Git 忽略。
2. 独立接口支持 URL、storageKey 和直接上传。
3. 所有 MinerU 请求固定使用精准解析 API 和 `vlm`。
4. 缺省 Provider 为 MinerU；`options.provider="local"` 和
   `options.provider="mineru"` 都能覆盖配置。
5. MinerU 可完成远程提交、轮询、结果下载和本地持久化。
6. MinerU Markdown、内容块、页码、坐标、表格和印章候选转换为本地 OCR 结构。
7. 新格式 `layout.json` 和旧格式 `*_middle.json` 都能完成页面尺寸、坐标和制品适配。
8. 结果写入 `ocr_jobs` 和 `ocr_parse_results`，原始产物写入 `ocr-artifacts`。
9. 绑定业务文档版本时调用现有 OCR 应用流程；独立请求不污染业务文档。
10. 错误、超时和不安全输入产生稳定诊断且不泄露秘密。
11. 新增测试及相关现有 OCR 回归测试全部通过。
