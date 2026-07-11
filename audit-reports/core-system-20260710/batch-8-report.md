# 第 8 批：前端操作与发布门禁

- 状态：**FAIL**
- 得分：**8 分**
- 基线：`bdd834860a28f99b16ce61f1c56b21fb18e01a63`

## 证据

- 641 后端测试、49 Playwright、TypeScript/lint/build 通过
- 28 个 route×viewport UI 审计零违规
- pip/pnpm 已知漏洞为 0
- 生产部署漂移且容器扫描证据缺失

## 问题

- **P1 DEPLOY-DRIFT-001**：生产部署与冻结基线存在漂移
- **P1 CRED-ROTATE-001**：模型网关凭据曾进入进程命令行可见范围
- **P2 RELEASE-EVIDENCE-001**：容器 SBOM/Trivy 和全部故障注入证据不完整
- **P2 PNPM-OVERRIDE-001**：pnpm 安全 override 配置被当前版本忽略
