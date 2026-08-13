# 2026-08-12 本地数据迁移结果

## 结果

- 迁移编号：`migration-20260812T124500Z`
- 目标连接：SSH `dev-bjy`（其配置使用 `ProxyJump jump`）
- 归档大小：`1,332,594,078` 字节
- 归档 SHA-256：`eef653d6e212451920b754740d50277f3889bac81241a47492ddb55152d1f100`
- PostgreSQL：完整覆盖 `aicheck`、`litellm`、`workflow`
- 全局角色：恢复用户自建角色；`aicheck` 口令校验值与源端一致
- 文件存储：源端实际使用 `local://`，而非 MinIO，因此迁移数据库引用闭包中的
  `output/document_uploads`、`output/knowledge_uploads` 和 `rules`
- 应用：API 已使用迁移后的数据库和持久化文件目录启动，演示数据与本地角色引导均关闭

## 验收证据

- 远端归档通过 SHA-256 校验并成功解包。
- 34,845 条非审计业务状态、2 条单例状态和 159 条幂等记录逐行摘要与源端一致。
- 147 个已迁移文件逐文件校验大小和 SHA-256，缺失 0、失配 0。
- `aicheck` 的 SCRAM 口令校验值摘要与源端一致；`hankieyooly` 的角色属性一致。
- `/readyz` 返回 `ready=true`，数据库、安全、运行时、工作流、模式和审计锚六项检查均通过，且认证开启。
- 验收期间使用未知默认口令产生了 6 条远端“登录失败”审计记录；除此之外业务状态与快照一致。

## 已知源端问题与目标端约束

- 清单记录了 9 个迁移前已缺失的文件引用：8 个旧 `Scan/*.pdf` 引用，以及
  `rules/standards/NB／T 47013-2015 承压设备无损检测-修订版.pdf`。这些不是传输丢失。
- 目标现有 PostgreSQL 集群的 `aicheck` 是 bootstrap 用户。PostgreSQL 不允许取消 bootstrap
  用户的 superuser 属性，因此其权限标志无法降为源端的普通登录角色；口令校验值已同步。
- 未持有业务账号明文口令，因此没有重置账号。数据库中的业务账号及密码哈希按快照原样保留。

## 服务器位置

- 迁移包：`/home/dev-bjy/aicheck-migrations/migration-20260812T124500Z`
- 持久化文件：`/home/dev-bjy/aicheck-data/files`
- 恢复回执：`/home/dev-bjy/aicheck-migrations/migration-20260812T124500Z/receipts/restore-receipt.json`
