# AIcheck 核心审计修复后复审

## 结论

- 环境：隔离预发布
- 基线分：**72/100**
- 修复后分：**82/100**
- 决策：**NO-GO**
- 剩余问题：P0 0、P1 3、P2 4

生产环境尚未部署本轮修复，生产结论仍以基线审计报告为准。

## 已修复

1. 上传会话创建、文件写入和完成改为关联记录增量 upsert，不再重写全部知识向量状态。
2. OCR worker 按当前 document/version 加载状态，单次状态加载从约 34 秒降至 0.333 秒。
3. OCR worker 使用显式删除集和 upsert 的同一事务，防止重跑后旧字段或旧证据复活。
4. OCR 结果增加 `outcomeStatus` 和 `formalEvidenceReady`；必填字段、表格、印章或 bbox 不完整时，文档进入“抽取不完整”，不再切片、向量化或材料自动定位。
5. 前端类型增加“抽取不完整”，保持现有 API 路径兼容。

## 预发布复审证据

- 完整写探针：`evidence/staging-write-probe-after-fix-v3.json`，`ok=true`。
- 文档级数据库状态加载：0.333 秒。
- OCR worker 测试 PDF：约 35 秒完成，其中主要耗时为远程 OCR 服务。
- 后端：648 项测试通过。
- 前端：typecheck、ESLint、Stylelint、production build 通过。
- 业务包：通过。
- 规范库质量：100.0。
- pip-audit：0 个已知漏洞。
- pnpm production audit：0 high、0 critical。
- Git LFS：`fsck OK`。
- 本机 OCR/Paddle/PaddleX/Docling 进程：0。

## 剩余 P1

1. `OCR-REAL-001`：服务器主 OCR 引擎仍会因内存不足失败；本轮只修复了 fail-closed 和状态真实性，没有提升识别准确率。
2. `DEPLOY-DRIFT-001`：生产 compose/镜像与冻结基线不一致，且 LiteLLM 仍存在可变标签部署。
3. `CRED-ROTATE-001`：审计中暴露范围内的模型网关凭据必须轮换，并禁止通过 argv 传递。

## 下一闸门

完成 OCR 服务容量治理、凭据轮换和不可变 digest 部署后，复跑第 3、7、8 批及 strict release gate；任一 P1 或 probe skip 存在时仍为 NO-GO。
