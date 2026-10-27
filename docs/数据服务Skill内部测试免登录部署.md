# 数据服务 Skill 内部测试免登录部署

本功能代码位于 `codex/lab-aicheck-workstations` 分支。服务器此前使用运行中容器补丁；从本分支构建后端镜像后无需再次手工复制 Python 文件。

## 代码与镜像

- `backend/libs/security/data_service_test_mode.py`：开关、HTTP 方法和路径白名单。
- `backend/apps/api/main.py`：测试接口免登录；忽略这些请求携带的旧令牌，使用部署默认租户。
- `backend/apps/api/mineru_ocr_routes.py`：共享测试身份、独立任务访问控制、按页读取 OCR 结果。
- `backend/apps/api/data_service_mcp_routes.py`：远程 Streamable HTTP MCP、临时 OCR 上传地址。
- `backend/libs/data_service_mcp_contract.py`：发布的工具参数契约，由 `scripts/sync_remote_mcp_contract.py` 生成。
- `backend/libs/data_service_ocr_result.py`：最终加工结果投影，保留文档级字段、全文质量、处理来源和未定位对象。
- `skills/aicheck-data-services/scripts/data_client.py`：客户端测试模式不发送 OCR 令牌。

`backend/Dockerfile.server`、`backend/Dockerfile.server-overlay` 已复制后端源码，构建时会包含上述模块。镜像构建上下文必须为 `backend`。本次没有重新构建或替换服务器镜像。

`backend/.dockerignore` 排除 `output/`，防止将原件、识别产物或测试开关烘焙进镜像。运行时仍需挂载持久化输出目录，并保证 API 用户可以读取开关。

## 开启和关闭

API 工作目录为 `/app` 时，开关文件为 `/app/output/data-services-noauth.enabled`，内容必须是 `enabled`。默认关闭；每次请求读取开关，变更无需重启。

当前服务器挂载的宿主目录为 `/home/dev-bjy/aicheck-data/files/output`。可由服务器管理员执行：

```sh
# 开启（文件属于运行配置，不提交 Git）
printf enabled > /home/dev-bjy/aicheck-data/files/output/data-services-noauth.enabled
# 关闭
rm -f /home/dev-bjy/aicheck-data/files/output/data-services-noauth.enabled
```

2.0 用户发布包采用远程 MCP：`http://39.108.65.148:8081/api/mcp/data-services`，WorkBuddy 类型为 `streamable-http`。导入包内 `mcp.workbuddy.json` 即可，不需要 Python、脚本路径、本地目录白名单或客户端环境变量。首次添加或修改地址后，WorkBuddy 可能要求启用或信任连接器。

旧 stdio 客户端才需要 `AICHECK_DATA_TEST_NOAUTH=1` 和 `AICHECK_ALLOW_HTTP=1`。关闭服务器测试开关后，远程 MCP 需要有效 Authorization 凭据。

OCR 工具先返回有效期 15 分钟的上传地址，宿主平台用 HTTP PUT 上传用户指定文件的原始字节，取得 jobId 后查询进度与结果。平台须具备文件上传或命令执行能力；远程服务器不能直接读取用户本机路径。签名密钥保存在 `output/mcp/upload-signing.key`，目录必须对 API 运行用户可写，并持久化挂载。

独立标准语料可通过 `AICHECK_INSPECTION_CORPUS` 指定；未设置时自动读取 `output/inspection-standard-corpus/corpus.json`，文件不存在则使用原有数据源。语料只允许标准资料，不允许工程资料。

## 范围与版本差异

开关仅放行标准能力/检索/全文、标准状态、证件有效期与登记查询，以及独立 MinerU 上传、任务状态、结果读取。工程、管理员接口及其他 HTTP 方法不在白名单内。

匿名 OCR 统一归属 `internal-data-services-test`。内部测试者共享该身份的新任务；无法借此读取其他用户、system 旧任务或工程绑定任务。不应将此身份误称为独立用户隔离。

本分支此前已将 `public_review_request` 指定的标准、规则和证件等接口设置为公开服务，这一已有策略保持不变。因此关闭测试开关将恢复 OCR 原有登录要求，不会撤销既有公开服务策略。远程旧版曾有 `_guard` 角色检查，服务器补丁暂时放行它；本分支已无此旧函数，无需补回。

## 验收

```sh
backend/.venv/bin/python -m pytest backend/tests/test_remote_data_mcp.py backend/tests/test_data_service_test_mode.py backend/tests/test_data_service_ocr_result.py skills/aicheck-data-services/tests -q
```

覆盖默认关闭、方法/路径边界、共享身份、旧任务与工程任务拒绝、OCR 结果页码及测试请求旧令牌不影响租户选择。部署后再验证 connection、证件有效期返回成功，管理员接口仍拒绝匿名访问。连接成功不代表重新执行过 OCR 或证件官方登记查询。

## 远程 MCP 验收记录（2026-09-29）

服务器沿用现有容器补丁，未重建镜像。Streamable HTTP 握手及 9 个工具发现通过；实测 GB/T 39280-2020 检索与第 7 物理页全文、随机无关查询返回空集、证件有效期计算均成功。使用不含个人信息的测试 PDF 完成临时 PUT 上传、MinerU 识别、分页文本和坐标读取，并确认 API 重启后仍可读取该任务。管理员接口匿名请求返回业务码 401。

本地远程协议、上传签名与过期、参数映射、免登录边界、OCR 结果、Skill 及标准语料测试共 18 项通过。测试文件、结果和部署用语料留在忽略目录，不打入 Skill 包。

WorkBuddy 本机已切换 URL 配置并识别 9 个工具；新对话实际完成 connection、standards、standard_content、ocr_result 四项调用。服务重启期间启动的会话可能没有工具索引，恢复后新建对话已验证可用。

## OCR 结果契约（2.1）

远程 `ocr_submit` 可选 `profileId`，可用值由 `connection.ocr.profiles` 返回。该参数进入签名上传凭证，上传时传给后台任务；不支持的类型在创建上传凭证前拒绝。

`ocr_result` 返回 `resultKind=processed_ocr`、最终 Profile、字段、表格、印章、处理来源和全文质量。分页只过滤有对应页码的对象；`documentFields` 及 `unlocatedContent` 保留没有可靠页码的数据，不能当作当前页内容。全文调用时与原数组重复，客户端展示需去重。

Worker 印章补识别后重新融合字段、计算质量，并更新 `normalized_json` 与哈希，保证保存的结果和 JSON 产物一致。`recognized=false`、`requiresHumanConfirmation=true` 的候选仍保留。坐标未映射与供应商置信度缺失警示不会因重新融合而消失。

`processing.postProcessing` 记录当前任务实际处理步骤，旧结果没有记录时 `provenanceAvailable=false`，不会自动回填或重新运行。当前服务使用共享内部测试身份；恢复正式鉴权时沿用既有任务访问控制。

部署须同步 API 的结果投影/契约/路由与 OCR Worker 的标准化/最终融合/持久化模块，待正在执行的任务结束后再重启对应 Worker。当前使用已有容器，不重建镜像；重建时使用本分支源码，并保留持久化目录。

## OCR 2.1 验收进展（2026-10-01）

本地协议、最终融合、产物一致性、资料类型路由、字段/表格提取、候选印章标记、分页和免登录测试共 99 项通过。Skill 结构校验、发布 ZIP 与各文件哈希检查通过，Codex 与 WorkBuddy 本机 Skill 已同步。

Codex 远程 MCP 实际 connection 与旧任务分页读取已通过，新任务的 profileId 已进入服务器记录。服务器固定数据运行验证提取 7 个焊工证字段及 1 张资格项目表，最终融合后的质量与 normalized_json 一致；旧提取器的表格没有 pageNo，保留在 unlocatedContent，不误归当前页。

两页合成扫描件包含测试专用印章，不含真实个人证件资料；真实上传任务 OCRJOB-BIZ-5506B382C5 在后台自动重试耗尽后于服务器时间 2026-10-02 01:33:32 结束为 failed，错误码 MINERU_JOB_TIMEOUT。等待期间供应商原始状态（保留 waiting-file 区分）确认为 pending，原件状态 uploaded；没有获得本次任务的 OCR 内容，完整线上验收未通过。未重复上传、未替换供应商、未将固定数据验证冒充新任务识别成功。测试与部署中间文件均位于忽略的 output/ 子目录。

## 服务器 OCR 验收问题修复（2026-10-01）

- 远程 MCP connection 明确返回 `ocrProvided=true`、`documentUploadAccepted=true`，输入与结果会在服务器保存；15 分钟只指上传票据有效期，不表示归档对象自动删除。外部识别提供商为 MinerU，connection 不宣称已执行识别。
- 已取得 providerTaskId 的 `MINERU_JOB_TIMEOUT` 使用独立接续预算 `AICHECK_MINERU_WAIT_RETRIES`（默认 24，范围 3–48），间隔 300 秒继续查询同一批次。单轮等待仍由 `AICHECK_MINERU_JOB_TIMEOUT_SECONDS` 控制。其他故障保留原有重试上限；超过接续预算仍明确失败，不无限等待。状态查询通过 `providerProgress.state` 区分供应商排队与处理。
- 生产 Compose 的文字检测、识别模型路径对齐已挂载的 `/models/official_models`。模型须预先下载到宿主模型目录；不通过伪造目录或忽略 readiness 使服务就绪。现有容器采用路径兼容链接，宿主模型文件已持久化。
- PaddleOCR 单次子进程默认内存上限与常驻子进程统一为 4096 MB，可用 `AICHECK_PADDLEOCR_MEMORY_LIMIT_MB` 调整。原 1536 MB 上限在实际模型推理时出现 `std::bad_alloc`；修复后合成图文字 `AICHECK OCR TEST 2026` 识别通过，readyz HTTP 200。

本次回归 100 项通过，2 项 PostgreSQL 集成测试因测试环境条件跳过。原超时批次在供应商完成后已实际接续成功，保存产物哈希与数据库、全文/分页结果一致。新任务 `OCRJOB-BIZ-D1FA382F0C` 在服务加载修复后仍使用原供应商批次，未再次上传；截至本次记录上游仍 pending，不能宣称新任务完整验收通过。模型和代码运行时补丁已应用于现有容器，没有重建镜像；当前分支保存了对应源码和部署配置。

2026-10-02 补充：状态接口返回面向宿主 AI 的 `statusMessage`、`recommendedPollSeconds` 和 `nextAction=poll_existing_job`，排队时建议 60 秒查询，解析中建议 15 秒查询；成功/失败状态不返回继续等待动作。不要把 `/api/v4/quota` 的零值直接解释为专属 API Token 额度耗尽：官方企业接口要求企业子用户标识，账户类型与调用条件未确认时必须保留“额度未核实”。
