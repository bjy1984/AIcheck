# 数据服务 Skill 内部测试免登录部署

本功能代码位于 `codex/lab-aicheck-workstations` 分支。服务器此前使用运行中容器补丁；从本分支构建后端镜像后无需再次手工复制 Python 文件。

## 代码与镜像

- `backend/libs/security/data_service_test_mode.py`：开关、HTTP 方法和路径白名单。
- `backend/apps/api/main.py`：测试接口免登录；忽略这些请求携带的旧令牌，使用部署默认租户。
- `backend/apps/api/mineru_ocr_routes.py`：共享测试身份、独立任务访问控制、按页读取 OCR 结果。
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

客户端 MCP env 增加 `AICHECK_DATA_TEST_NOAUTH=1`。当前测试地址为 `http://39.108.65.148:8081`，HTTP 兼容项为 `AICHECK_ALLOW_HTTP=1`。恢复 OCR 鉴权时移除免登录变量，配置远程有效令牌并重新加载 MCP；WorkBuddy 配置变更可能需要重新信任。

## 范围与版本差异

开关仅放行标准能力/检索/全文、标准状态、证件有效期与登记查询，以及独立 MinerU 上传、任务状态、结果读取。工程、管理员接口及其他 HTTP 方法不在白名单内。

匿名 OCR 统一归属 `internal-data-services-test`。内部测试者共享该身份的新任务；无法借此读取其他用户、system 旧任务或工程绑定任务。不应将此身份误称为独立用户隔离。

本分支此前已将 `public_review_request` 指定的标准、规则和证件等接口设置为公开服务，这一已有策略保持不变。因此关闭测试开关将恢复 OCR 原有登录要求，不会撤销既有公开服务策略。远程旧版曾有 `_guard` 角色检查，服务器补丁暂时放行它；本分支已无此旧函数，无需补回。

## 验收

```sh
backend/.venv/bin/python -m pytest backend/tests/test_data_service_test_mode.py backend/tests/test_data_service_ocr_result.py skills/aicheck-data-services/tests -q
```

覆盖默认关闭、方法/路径边界、共享身份、旧任务与工程任务拒绝、OCR 结果页码及测试请求旧令牌不影响租户选择。部署后再验证 connection、证件有效期返回成功，管理员接口仍拒绝匿名访问。连接成功不代表重新执行过 OCR 或证件官方登记查询。
