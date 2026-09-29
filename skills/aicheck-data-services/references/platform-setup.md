# 安装和服务器连接

用户发布版优先使用 [安装说明](../安装说明.md) 中的配置向导，自动填写 Python、脚本及本机资料目录；以下 JSON 用于手动配置。

如果脚本自检成功但平台仍显示未连接，请在 WorkBuddy 中检查该 MCP 是否已启用、已信任，以及配置是否保存到当前使用的环境；重新加载连接器或重启平台后再次实际调用 connection。离线文件读取成功不代表 MCP 已连接。不要因此重复上传资料。

解压到固定目录，导入SKILL.md。MCP使用Python 3.10+标准库，不需要用户安装项目后端或MinerU模型。此版本为本地stdio桥接远程HTTP服务，不是已上架的WorkBuddy连接器，也不宣称已提供远程Streamable HTTP MCP。

合并以下配置到宿主MCP配置；用真实服务器地址、脚本位置和允许读取目录替换示例：

```json
{
  "mcpServers": {
    "aicheck-data-services": {
      "type": "stdio",
      "command": "python3",
      "args": ["/absolute/path/aicheck-data-services/scripts/mcp_server.py"],
      "env": {
        "AICHECK_BASE_URL": "https://your-aicheck-server.example",
        "AICHECK_TOKEN_FILE": "/absolute/private/path/aicheck-token.txt",
        "AICHECK_DATA_ALLOWED_ROOTS": "[\"/absolute/path/user-selected-files\"]"
      },
      "disabled": false
    }
  }
}
```

远程使用HTTPS，本地联调可使用http://127.0.0.1:8000。OCR使用服务器账号登录令牌，标准/证书服务保持各自现有鉴权策略；配置文件不得包含服务器MinerU供应商密钥。无需给用户项目源码路径。

启用并信任MCP后，重新加载工具列表。工具前缀为aicheck_，共9个：connection、ocr_submit、ocr_status、ocr_result、standards、standard_content、standard_status、certificate_registry、certificate_validity。其他同名MCP由宿主通过服务器名区分，避免选错旧审查连接器。

## 服务器部署要求

复用现有 `/api/internal/ocr/mineru/tasks/upload` 和任务状态接口，需运行项目API、持久化、存储及MinerU任务worker，配置供应商凭据。新增加 `/api/internal/ocr/mineru/tasks/{jobId}/result` 供授权用户读取规范化结果，服务器须部署本次代码后才可用。没有projectId/documentId，不创建工程或工程文件版本。

原始OCR产物遵循现有服务器artifactReferences，其结构可能与标准库sidecar目录不同。此包读取规范化JSON，不承诺下载本机不可访问的服务器路径。当前接口没有独立删除/取消和自动24小时过期承诺；原件、任务及产物按实际服务器策略保留，需运维清理。不要把原先方案建议的临时留存期限当成已实现功能。

## 验收

1. 调用connection检查标准全文能力；credentialsConfigured只说明配置项存在，不证明令牌有效。
2. 用用户指定的测试文件调用ocr_submit，提供随机UUID作为requestId。
3. 保存jobId，按返回状态轮询；成功后按pageNo读取ocr_result，与原件核对。
4. 检索明确标准编号，再读取返回fileId的原文，核对版本及页码。
5. 使用测试证件字段验证有效期覆盖和缺日期；官方登记只报告真实工具结果。
6. 输入超出允许目录的路径、越界页码及其他账号任务，验证拒绝。

任务失败保留原始错误码，不自动换供应商或反复重新上传。OCR原文过大时按页获取。格式仅支持PDF、PNG、JPEG，客户端限100MB。

## 内部测试免登录模式

仅当管理员已开启服务端测试开关时，在 MCP env 增加 `AICHECK_DATA_TEST_NOAUTH=1`；公网 HTTP 测试地址还需 `AICHECK_ALLOW_HTTP=1`。该模式不发送 OCR 令牌，共享测试身份的独立 OCR 任务可被其他测试者读取，已有用户/工程任务仍受保护。

服务端在 API 工作目录的 `output/data-services-noauth.enabled` 写入 `enabled` 即开启；删除此文件即时关闭。仅放行标准、证件与独立 OCR 指定接口。关闭时同步移除客户端免登录变量并配置有效令牌。发布部署须包含 `libs/security/data_service_test_mode.py` 和对应路由改动；容器重建必须使用包含本次修改的镜像。
