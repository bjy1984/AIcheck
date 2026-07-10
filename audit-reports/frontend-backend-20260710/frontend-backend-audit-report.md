# AIcheck 前后端联合上线审计

## 结论

**NO-GO，65/100。** 当前代码的业务状态机、confirmed-only 证据链、知识库与 ROI 质量具备较好基础，但鉴权存在可复现的 P0 绕过，生产依赖图也包含 critical/high 漏洞。按“P0/P1 为 0”的上线硬门槛，当前不能稳定上线运营。

本次仅执行审计并生成报告，没有修改前端、后端或业务规则。所有 OCR/视觉重任务均未在本机运行。

## 评分

| 维度 | 得分 | 满分 | 结论 |
| --- | ---: | ---: | --- |
| 业务状态机 | 22 | 25 | 后端硬闸门较完整，前端重复入口存在 readiness 不一致 |
| 证据与 AI 正确性 | 18 | 20 | confirmed-only、知识/ROI 审计通过，缺少远程活体链路证据 |
| 权限与数据隔离 | 3 | 15 | dev-token 鉴权旁路构成 P0 |
| 任务与存储可靠性 | 8 | 15 | 静态检查通过，但没有生产型故障注入和写探针 |
| 前端操作质量 | 10 | 15 | 静态检查通过，Playwright 43/44，通过率非 100% |
| 部署与可观测性 | 4 | 10 | 本地环境不是生产拓扑，依赖和部署可重复性不足 |
| **总计** | **65** | **100** | **NO-GO** |

## 已验证基线

- Git：`main` 与 `origin/main` 一致，提交 `c2d571f89c20644a6dc532e06f3c483aadd55a5b`，LFS 完整性通过。
- 后端：`605 passed`；前端 typecheck、ESLint、Stylelint、production build 通过。
- Playwright：`43 passed / 1 failed`。失败来自管理员项目页两个同名“新建项目”控件。
- 前后端合同：230 个前端接口调用，后端 656 个路由键，缺口 0。
- 业务包：100 分；规范库质量：100 分，60/60 文件、2134/2134 vectors；ROI：100 分。
- SQLite 基线 quick check：`ok`。这只证明本地开发库完整，不代表生产 PostgreSQL/MinIO/Redis/Temporal。
- 静态部署报告：35 pass、0 fail、1 skip；本地只读 live 报告：48 pass、2 fail、14 skip。
- 本地 live 环境为 SQLite、免认证、demo 用户、无 PostgreSQL/MinIO，不可作为生产上线证据。

## 上线阻断项

1. **P0 AUTH-001**：`decode_token` 无条件信任 `dev-token-*`，低权限持久用户可用伪造 token 自声明 admin。实测请求 `/admin/users` 被接受。
2. **P0 DEP-001**：前端 production dependencies 有 1 critical、27 high；后端环境发现 17 个漏洞，包含 LiteLLM 鉴权绕过、权限提升和代码执行相关问题。
3. **P1 AUTH-002/003**：新用户默认密码等于用户名，存在 `plain:` 回退；公开 mock 用户接口泄露 `passwordHash`，生产登录页还展示测试账号和密码规则。
4. **P1 SEC-004**：CORS 为 wildcard + credentials，登录路径没有可验证的速率限制。
5. **P1 PIPE-001**：没有可验证的预发布端点和已轮换凭据，因此未完成上传到归档写探针、远程 OCR/Qwen 活体探针及故障注入。
6. **P1 DEP-002**：LiteLLM 使用 `main-latest`，部署内容不可复现。

## 前端业务流程

- inspection 零证据节点：面板 AI 复核正确禁用，但顶栏“重新核验”仍可点击。
- NDT 零报告场景：面板提交正确禁用并展示 blocker，但顶栏“提交检测资料”仍可点击。
- 后端会阻断上述错误推进，因此数据完整性风险暂未转化为正式状态错误；用户仍会遭遇可预见的 409/失败提示。
- 浏览器可访问性采样发现低对比度文本、低于 44px 的交互控件和无可访问名称控件。
- 控制台出现 `/workbench/inspection` 无匹配路由和 Element Plus pagination 弃用警告。

## 未完成探针

以下项目没有被计为通过：生产型 MinIO 上传、远程 OCR object probe、Qwen server/official API 实际调用、Redis/worker/Temporal/MinIO 故障注入、归档对象不可变性。原因是未提供可验证的预发布环境和已轮换的最小权限凭据。对话中曾出现的 SSH/API 凭据按泄露处理，本次没有复用。

## 修复优先级

1. 关闭生产 `dev-token` 路径，按持久用户角色授权；移除生产 mock 路由和弱密码默认值。
2. 将依赖 critical/high 清零，锁定 LiteLLM 镜像 digest，生成 SBOM。
3. 收紧 CORS、增加鉴权限流，把上述安全探针加入 strict deployment gate。
4. 统一 Workbench 顶栏和面板 readiness，修复 Playwright 失败与可访问性问题。
5. 在隔离预发布完成全链路写探针和服务故障注入，获得当前提交的可追溯证据后重新审计。

详细复现和建议见 `findings.json`，业务时序映射见 `business-flow-matrix.json`。
