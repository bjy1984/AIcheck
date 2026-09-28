# 安装与连接

将包解压至任意固定目录。MCP 宿主与文件必须在同一机器；云端平台不能直接访问 Mac 的绝对路径。需要 Python 3.10+ 启动 stdio，以及已安装项目后端依赖的 Python。此包不是独立 OCR 模型，不包含项目源码、模型和密钥。

在支持本地 stdio MCP 的平台添加以下配置（合并到已有 mcpServers，不覆盖其他服务）。下面是当前 Mac 的路径示例，其他机器必须修改：

```json
{
  "mcpServers": {
    "aicheck-ocr": {
      "type": "stdio",
      "command": "/opt/homebrew/bin/python3",
      "args": ["/Users/mac/Documents/AIcheck/skills/aicheck-ocr/scripts/mcp_server.py"],
      "env": {
        "AICHECK_OCR_PROJECT_ROOT": "/Users/mac/Documents/AIcheck",
        "AICHECK_OCR_PYTHON": "/Users/mac/Documents/AIcheck/backend/.venv/bin/python",
        "AICHECK_OCR_ALLOWED_ROOTS": "[\"/Users/mac/Documents/AIcheck\",\"/Users/mac/WorkBuddy\"]",
        "AICHECK_OCR_OUTPUT_DIR": "/Users/mac/.aicheck/ocr-results"
      },
      "disabled": false
    }
  }
}
```

项目后端 `.env` 由后台任务加载；既有环境变量优先。MinerU 使用 `AICHECK_MINERU_API_KEY` 等既有配置；千问使用项目 OCR runtime 配置与 `AICHECK_ALIYUN_OCR_API_KEY`。不要把密钥放入发布包。无需启动网页/API/工程数据库服务，直接复用项目 Python 引擎；具体引擎自身的网络、缓存依赖仍须可用。

## 验收

1. 平台启用并信任该 MCP 后，重启连接/新开会话。
2. 实际调用 `aicheck_ocr_connection`，参数 `{}`。应列出 `runtime`、`mineru` 和配置情况。
3. 调用 `aicheck_ocr_start`：`{"filePath":"/绝对路径/样本.pdf","engine":"mineru"}`。
4. 调用 `aicheck_ocr_result`：`{"taskId":"返回的任务ID","pageNo":1}`。等待终态，核对文字、页码、表格和原件。

单文件上限100MB；页数受项目runtime上限约束；最多两个活跃任务（单宿主正常顺序提交）。没有取消接口，后台任务随引擎超时结束。运行结果含本地资料，按需要手动删除输出目录中的已完成任务目录。

## 已配置但未连接

- 脚本/解释器可运行不证明平台已启用：检查平台 MCP 信任、启用开关和启动日志。
- `notConfigured`：检查项目路径、允许目录 JSON 或供应商密钥。
- `pathNotAllowed`：将用户资料所在目录加入允许目录；不扩大到整个磁盘。符号链接按真实路径检查。
- `runtimeUnavailable`：检查后端虚拟环境与依赖，不能用仅有标准库的启动解释器替代后端环境。
- `failed`：查看 result 返回的错误码。配置检测与外网真实识别是两项独立验收。
- 更新脚本后重启 MCP；若只是后端 `.env` 变更，新提交任务会重新加载，无需重新导入 Skill。
