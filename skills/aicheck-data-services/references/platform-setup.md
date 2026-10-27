# 远程 MCP 连接与部署

用户安装见 [安装说明](../安装说明.md)，配置文件见 [mcp.workbuddy.json](../mcp.workbuddy.json)。发布包无需本地执行脚本。仓库保留 scripts/ 中的旧 stdio 实现供兼容测试，不作为远程版用户安装步骤。

## 服务契约

- 地址：`http://39.108.65.148:8081/api/mcp/data-services`
- 传输：Streamable HTTP，JSON响应，无会话存储。协商2025-06-18或2025-03-26协议；GET不提供SSE流，返回405。
- 9个工具：connection、standards、standard_content、standard_status、certificate_registry、certificate_validity、ocr_submit、ocr_status、ocr_result，统一aicheck_前缀。
- ocr_submit只签发临时PUT上传地址，上传完成才返回jobId。不能接收服务器路径、任意远程URL或代为读取用户电脑。
- 浏览器Origin默认拒绝，管理员可用AICHECK_MCP_ALLOWED_ORIGINS明确配置允许列表。

## 版本更新

2.3.1 增加问题导向的专项求证与输出样例，仅更新 Skill 指令和参考资料；MCP 工具名称、参数及远程地址不变。导入新版后新建对话读取新约定，不需要重配连接器。

2.2.0 同步服务端自动切换策略：MinerU 连续 pending 默认 60 秒后由千问接管，保留原 jobId。Skill 指导读取实际引擎、切换原因、逐页进度以及质量状态，不宣称官方任务取消成功。已有远程连接无需改 URL 或凭据；更新 Skill 后新建对话，让宿主读取新版说明。工具名称和提交参数不变。

2.1 新增 `ocr_submit.profileId` 和最终加工结果的来源、全文质量、未定位字段。更新 Skill 后重载连接器或新建对话，刷新平台缓存的工具定义；远程 URL 和原有连接配置不用改。若平台仍提示 profileId 为多余参数，先刷新工具定义，不将其误报为服务无法识别资料。已有任务没有处理来源记录时会明确标记，不会自动重新 OCR。

## 管理员部署

后端新增 `apps/api/data_service_mcp_routes.py` 和生成契约 `libs/data_service_mcp_contract.py`。工具契约变更后运行 `scripts/sync_remote_mcp_contract.py` 更新生成文件。

MCP通过固定回环地址 `http://127.0.0.1:8000/api` 复用已有接口。上传签名密钥自动生成于 `output/mcp/upload-signing.key`，目录需仅对服务账号可写并持久化，密钥不进镜像或发布包。`AICHECK_MCP_PUBLIC_BASE_URL` 配置外部上传入口，默认当前测试服务器地址。

内部测试免登录沿用 `output/data-services-noauth.enabled` 开关，仅开放指定MCP与上传路径；关闭后恢复后台原有鉴权。前端客户端无需配置AICHECK_ALLOW_HTTP或AICHECK_DATA_TEST_NOAUTH。管理员及工程接口不放开。

沿用现有 OCR 队列、数据库及对象存储，增加千问接管分支。`AICHECK_MINERU_PENDING_TIMEOUT_SECONDS` 默认 60；千问使用专用 OCR 凭据，未配置时仅允许复用同一地域官方 DashScope 视觉凭据，不混用 Token Plan 密钥。客户端不负责配置后台的引擎密钥。任务和原件仍按已有策略留存，没有新增自动清理承诺。部署后需验证真实远程握手、工具调用和上传，不以本地单元测试替代服务器验收。
