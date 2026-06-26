# UI 静态交互页面映射

更新时间：2026-06-25

## 范围

本次补齐 `ui` 目录内现有静态设计页中可点击控件的二级页面或页面内跳转，包括：

- `contractor_workbench.html`
- `inspection_workbench.html`
- `ndt_workbench.html`
- `owner_workbench.html`
- `admin_backend.html`
- `role_workbenches_static.html`
- `workbench_file_package_mockups.html`

新增文件：

- `static_ui_interactions.html`：所有二级静态页面的集合，通过 hash 定位到具体子页面。
- `static_ui_nav.js`：统一把原型中的按钮、无 `href` 操作链接、顶部搜索、待办、消息、用户入口、项目树节点和上传区域跳转到对应静态页面。

## 公共入口映射

| 触发入口 | 静态目标 |
| --- | --- |
| 顶部全局搜索、文件/节点/底片编号搜索 | `static_ui_interactions.html#global-search` |
| 待办、提醒、配置待办 | `#todo-center` |
| 消息 | `#message-center` |
| 用户信息 | `#user-menu` |
| 项目树节点 | `#node-detail`，无损检测节点进入 `#ndt-node-detail` |
| 放大、缩小 | `#preview-zoom` |
| 下载 | `#download-center` |
| 定位证据、定位反馈、定位底片、定位意见 | `#evidence-locator` |
| 刷新、筛选、齿轮设置 | `#refresh-state` 或 `#filter-settings` |
| 只看未挂载、只看需补正 | `#filter-settings` |

## 施工方映射

| 触发入口 | 静态目标 |
| --- | --- |
| 批量上传文件、选择文件、上传补正附件、上传区域 | `#contractor-upload` |
| 选择挂载节点、未挂载文件挂载 | `#contractor-mount-node` |
| 提交本批文件及挂载关系、提交选中文件、提交补正反馈 | `#contractor-submit` |
| 保存草稿 | `#draft-save` |
| 撤回未提交 | `#withdraw-submit` |
| 查看历史版本 | `#file-history` |
| 补正反馈 | `#feedback-correction` |
| 查看/替换、查看文件 | `#file-detail` |
| 查看反馈、关联意见 | `#feedback-detail` |

## 监检映射

| 触发入口 | 静态目标 |
| --- | --- |
| 重新核验、重新推理 | `#ai-recheck` |
| 查看规则版本 | `#rule-version` |
| 复制业务结论、复制结论 | `#copy-conclusion` |
| 挂载文件 | `#inspection-mount-file` |
| 上传监检资料 | `#inspection-upload` |
| 保存审查意见、保存意见 | `#inspection-opinion` |
| 采纳 AI 建议、采纳结果 | `#ai-adopt` |
| 驳回 AI 建议、驳回结果 | `#ai-reject` |
| 退回补正 | `#return-correction` |
| 报告生成/复核 | `#report-review` |
| 查看日期比对 | `#date-compare` |
| 查看条款、标准依据 | `#standard-reference` |
| 查看证据链 | `#evidence-chain` |

## 无损检测映射

| 触发入口 | 静态目标 |
| --- | --- |
| 新增底片编号 | `#ndt-film-add` |
| 批量导入记录、批量导入 | `#ndt-import` |
| 上传检测报告、检测报告上传区 | `#ndt-upload-report` |
| 按节点挂载资料 | `#contractor-mount-node` |
| 提交检测资料 | `#ndt-submit` |
| 查看监检意见 | `#inspection-feedback` |
| 补正反馈 | `#feedback-correction` |

## 建设方映射

| 触发入口 | 静态目标 |
| --- | --- |
| 导出状态摘要 | `#export-center` |
| 刷新状态 | `#refresh-state` |
| 预览报告 | `#owner-report-preview` |
| 浏览归档资料、报告归档节点 | `#archive-browser` |
| 查看节点资料摘要、项目总览 | `#owner-node-summary` |
| 只读说明 | `#readonly-scope` |

## 管理后台映射

| 触发入口 | 静态目标 |
| --- | --- |
| 项目列表、项目台账 | `#project-list` |
| 项目详情、打开项目详情 | `#project-detail` |
| 项目立项、项目立项向导、新建项目、创建项目 | `#project-create-wizard` |
| 组织用户、组织机构、用户账号 | `#org-users` |
| 角色权限配置、菜单权限、接口权限、审核动作权限 | `#role-permission` |
| 项目成员授权、成员授权 | `#project-member-auth` |
| 流程状态机、流程管理 | `#workflow-state-machine` |
| 待办规则、待办规则配置 | `#todo-rule-config` |
| 流程实例详情、查看流程实例 | `#workflow-instance-detail` |
| 项目审核节点维护 | `#admin-node-tree` |
| 节点与角色权限矩阵 | `#admin-permission-matrix` |
| AI 业务审查规则模板、新增规则模板、复制模板、编辑模板 | `#admin-rule-template` |
| AI 知识库管理、知识库总览、项目文件知识库、OCR/向量任务中心、多 LLM 反馈对比 | `ai_knowledge_base_admin.html` |
| 外部核验工具源配置 | `#admin-tool-source` |
| 证据字段映射配置、配置字段 | `#admin-field-mapping` |
| 角色维护、单位管理、人员维护、人员与角色绑定 | `#admin-people-role` |
| 查看版本 | `#admin-version` |
| 导出配置 | `#admin-export` |
| 审计、操作日志 | `#audit-log` |

## 组合原型 Tab 映射

| 触发入口 | 静态目标 |
| --- | --- |
| 节点文件 | `#tab-node-files` |
| 资料预览 | `#tab-preview` |
| OCR 识别 | `#tab-ocr` |
| AI 审查 | `#tab-ai-review` |
| 标准依据 | `#standard-reference` |
| 审查记录 | `#tab-review-log` |

## 设计说明

- 现有工作台页面保持原有静态布局，仅新增统一跳转脚本。
- 二级页面集中在 `static_ui_interactions.html`，每个目标都是真实 HTML section，可直接通过 URL hash 打开。
- `role_workbenches_static.html` 的角色切换按钮仍保留原有页面内切换行为；其余业务按钮跳转到二级静态页面。
- 建设方相关页面保持只读边界，不出现上传、审查、退回、报告确认等办理按钮。
- 管理后台只展示配置类页面，不承载项目审查办理动作。
