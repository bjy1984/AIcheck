# 阶段 4 · 安全与角色隔离审计

审计对象：认证/授权链路、四方角色（inspection/contractor/ndt/owner）+ admin/FDE 的可见性与操作边界、上传链路、密钥管理。

**总体结论**：授权体系是「全局中间件（成员资格 + 节点范围）+ 写操作动作矩阵」的两层设计，
在 `AICHECK_REQUIRE_AUTH=true` 下项目/节点级隔离是完备的；主要风险是**整个授权体系单点依赖这一个环境变量**，以及**角色级读裁剪未实现**。

---

## S-1 · 认证开关默认关闭，且关闭时授权层同时失效 【P1】

**位置**：[main.py:372 `auth_required`](../../backend/apps/api/main.py)（代码默认 `false`）；
[routes.py:2894-2897 `authorized_node_scope`](../../backend/apps/api/routes.py)、
[routes.py:1954-1956 `member_node_scope_error`](../../backend/apps/api/routes.py)。

关闭认证时的连锁效应（逐条实证）：
1. 全局项目授权中间件 `inferred_project_scope_error` 开头 `if not claims: return None` → 直接放行；
2. `authorized_node_scope`：`user_id` 为空 → `return None`（= 无限制可见）；
3. `member_node_scope_error`：`if not user_id: return None` → 放行；
4. `X-Role`/`X-User-Id` 头可任意声明（[routes.py:366](../../backend/apps/api/routes.py) 默认落 `inspection`）。

即：**这不只是「认证关闭」，而是认证 + 项目隔离 + 节点范围 + 角色校验四层同时归零**。
compose 默认 `true`、DEPLOYMENT.md 也强调了；但任何绕过 compose 的部署（本地裸起、k8s 手写 manifest、
CI 环境）都会静默进入全开状态，且无启动警告。

**建议**：默认值改 `true`；或保持 `false` 时启动打印显著警告 + `/readyz` 暴露 `authRequired` 状态（现仅在 ui-context 暴露）。

---

## S-2 · 读端点缺少 handler 层防御，完全依赖中间件正则 【P2】

**扫描结果**：至少 5 个项目级 GET 端点自身无任何访问检查，安全性完全依赖
[main.py:229](../../backend/apps/api/main.py) 中间件的路径正则推断：

```
GET /projects/{pid}/inspection/nodes/{nid}/review-opinions   ← 人工结论全文
GET /projects/{pid}/documents/{did}/original                 ← 原始文件下载
GET /projects/{pid}/documents/{did}/versions
GET /projects/{pid}/workflow
GET /projects/{pid}/inspection/nodes/{nid}/evidence-chain
```

中间件在 auth 开启时确实覆盖了成员资格 + 节点范围（含 documentId→节点反查），当前无洞。
但这是**单层防御**：中间件用正则从 URL 提取 scope（`/nodes/(\d+)`、`/documents/([^/]+)`），
新增路由若命名不匹配正则（如 `/node-groups/`、query 传 id），中间件静默漏判，handler 又无兜底。
30k 行路由文件的演进速度下，回归风险高。

**建议**：为高敏读端点（人工结论、原始文件、证据链）补 handler 层 `member_node_scope_error` 调用（写端点已普遍这样做，读端点如 `list_ai_runs` 也有——补齐这 5 个即可对齐现有惯例）。

---

## S-3 · 角色级读裁剪未实现：同节点内四方看到同样的数据 【P2·需业务确认】

**现状**（代码即事实）：可见性模型 = 成员资格 + `nodeScope`，**角色只约束写操作**
（动作矩阵仅在 mutation/`X-Action-Code` 路径生效）。节点范围内：
- **contractor** 可读该节点的 `review-opinions`（监检人工结论全文）、`ai-runs`（AI 判定结果与理由，
  `safe_ai_run_view` 只裁剪 prompt/原始 OCR，保留 findings/suggestion）、`evidence-chain`；
- **owner**（observer 定位）同样可读逐条不符合项与 AI 理由，并非「只看汇总进度」；
- **ndt** 若被授权某节点，可读施工方在该节点的资料与结论。

与最小权限默认口径（施工方不见 AI 理由、建设方只见汇总）不一致。若业务接受「进了节点范围就全可见」，
此项关闭；否则需按角色做读端点响应裁剪。

**建议**：与业务方确认后二选一：确认现状（在文档固化）或实现角色级响应裁剪（contractor 隐去 opinion 全文与 AI 理由、owner 聚合视图）。

---

## S-4 · 其他

- 【P3】auth 关闭时 `X-User-Id` 直接作为 actor 身份写入审计日志（[routes.py:1815](../../backend/apps/api/routes.py)）——审计记录可被伪造身份。随 S-1 修复。
- 【P3】`request_user_id` 在 auth 开启但 token 无对应用户快照时回退信任 `X-User-Id` 头——实际主流程已有 identity 校验拦截，属冗余路径，建议删除回退。

---

## 做对的部分（审计确认）

- **写操作矩阵完备**：owner 全写禁止、FDE 禁业务写、admin 不能代存审查意见、角色-动作矩阵 + 路径自动推断 ActionCode（[routes.py:1758-1794](../../backend/apps/api/routes.py)、[main.py:698](../../backend/apps/api/main.py)）。
- **身份一致性**：JWT role/authVersion/租户三重校验，会话吊销检查，头与 token 不一致直接 403（[main.py:174-230](../../backend/apps/api/main.py)）。
- **上传链路**：`safe_upload_file_name` 清洗（反斜杠/控制字符/保留字符）、`safe_relative_path` 去 `..`、大小与类型白名单校验；两处 `store_knowledge_upload` 调用点均先清洗——未发现路径穿越。
- **密钥**：生产标志开启时强制显式 `LITELLM_API_KEY`，内置 dev key 被拒（[litellm_client.py:26-30](../../backend/libs/integrations/litellm_client.py)）。
- **LLM 数据面**：`safe_ai_run_view` 对外裁剪 rawPrompt/rawOcrText/messages，仅留哈希摘要。
- **幂等与并发**：Idempotency scope 含租户 + actor + 角色；ETag/If-Match 乐观锁；409 冲突回滚。
