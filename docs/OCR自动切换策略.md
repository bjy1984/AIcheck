# MinerU 排队超时切换千问 OCR

## 行为

默认先使用 MinerU 精准解析 VLM。连续 `pending` 达到 `AICHECK_MINERU_PENDING_TIMEOUT_SECONDS`（默认 60 秒，0 表示立即切换）后，在同一个 OCR job 内切换千问。`pendingSince` 和 `activeProvider` 持久化；重启不重置持续排队计时，千问重试不重新提交 MinerU。进入 running/converting 时清除排队计时，仍使用原解析超时策略。

切换会停止本系统的 MinerU 轮询和重试。官方公开 API 未确认取消接口，因此 `fallback.remoteCancellation=unsupported`，不宣称官方任务已取消。切换后的执行只接收千问结果。

## 任务与结果

- 数据库 `provider=mineru` 保留为原任务的队列路由；`activeProvider=qwen` 记录当前执行分支。
- 对外 `provider/model` 返回实际执行来源；原 MinerU 编号保留在 `fallback.providerTaskId`。
- HTTP/MCP 保持原 jobId，返回切换原因、逐页进度和最终结果，无须重新上传。
- 使用共享的 PostgreSQL advisory lock（带保活）串行执行同一租户、同一 job；断锁后拒绝提交结果。非生产无数据库环境使用进程内锁。
- 千问复用 `official_ocr_extract`：逐页文字、表格与字段识别、印章候选处理、原文定位核验，以及已有 profile 后处理与质量检查。
- 页级 checkpoint 放对象存储，重试读取已完成页。千问暂时性失败最多执行三轮，不切回 MinerU。
- 独立上传直接保存结果；绑定工程的资料复用原有结果应用、分类及切片派发，仍遵守项目资料索引开关。
- 输出保存 `raw_qwen_json`、`normalized_json`、`markdown`，不伪造 MinerU ZIP。缺页、截断、缺项和人工复核标记保留。

## 配置与依赖

优先配置 `AICHECK_ALIYUN_OCR_API_KEY` 和对应官方 OCR endpoint。未配置专用密钥时，仅当 `AICHECK_LLM_VISION_API_BASE` 与 OCR endpoint 是同一个受支持的官方 DashScope 地域域名时，才复用 `AICHECK_LLM_VISION_API_KEY`。不复用通用 LLM、Token Plan 或第三方密钥。

生产环境需要可用的 PostgreSQL、Redis、对象存储和千问 OCR 模型权限。Office 输入复用 LibreOffice 转 PDF；未安装转换程序时明确失败，不将文件当图片处理。公开 URL 输入使用受限 HTTPS 下载，校验并固定公网解析地址，重定向逐跳校验，并限制文件体积。

## 验收

回归测试位于 `backend/tests/test_ocr_failover.py`，覆盖持续排队计时、分支恢复、重复执行、质量与归档内容保留、页码范围、访问地址校验、凭据地域隔离以及锁丢失。真实测试资料和结果位于忽略 Git 的 `output/ocr-failover-acceptance/`。
