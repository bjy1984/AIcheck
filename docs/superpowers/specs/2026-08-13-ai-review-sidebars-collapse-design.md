# AI Review 左右侧栏收起展开设计

## 背景

独立 `/ai-review-b` 页面采用左侧节点导航、中间对话、右侧上下文的三栏布局。当前左右侧栏固定占宽，页面没有释放对话空间的入口。`/workbench/inspection` 的外层节点栏已有成熟的收起交互，但独立 AI Review 页面未复用该能力。

## 目标

- 为独立 `/ai-review-b` 的左侧节点栏和右侧上下文栏分别增加收起、展开动作。
- 两侧默认展开，状态相互独立。
- 任一侧收起后，中间对话区自动获得释放的空间。
- 保持收起后的操作入口可见且支持键盘和读屏器。
- 仅发布前端，不重启 API。

## 非目标

- 不修改监检用户默认路由。
- 不修改后端接口、认证、数据库或部署配置。
- 不改变 `/workbench/inspection` 的内嵌 AI Review 布局。
- 不持久化侧栏状态到本地存储或用户配置。

## 交互设计

页面增加两个独立布尔状态：`leftSidebarCollapsed` 和 `rightSidebarCollapsed`，初始值均为 `false`。

每个侧栏边界放置一个圆形按钮：

- 展开时，按钮文案和辅助标签为“收起节点导航”或“收起上下文”。
- 收起时，按钮文案和辅助标签改为“展开节点导航”或“展开上下文”。
- 按钮使用 `aria-expanded` 表示对应区域状态，并用 `aria-controls` 关联内容区域。
- 图标随状态旋转，使方向与动作一致。

收起时不删除侧栏节点，而是将内容设为不可交互并隐藏，保留 28px 操作轨道和按钮。这样展开入口始终可见，也避免重新创建节点树或上下文表单造成状态丢失。

## 布局

独立模式默认列宽保持现状：

```text
minmax(300px, 404px) minmax(650px, 1fr) 330px
```

根据两个状态组合切换 Grid：

- 仅左侧收起：`28px minmax(650px, 1fr) 330px`
- 仅右侧收起：`minmax(300px, 404px) minmax(650px, 1fr) 28px`
- 两侧收起：`28px minmax(650px, 1fr) 28px`

窄屏媒体查询采用相同的 28px 轨道规则。内嵌模式不添加状态类，也不渲染按钮，继续使用现有两栏布局。

## 文件与边界

只修改：

- `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`
- `frontend/src/views/AIReviewB/embeddedReviewWorkbench.test.ts`

组件现有数据请求、节点选择、对话、证据和人工结论逻辑均保持不变。

## 测试与发布

- 先增加失败的源码契约测试，验证左右状态、按钮、ARIA 属性和四种 Grid 类存在。
- 运行全部前端单测和 TypeScript 检查。
- 运行生产构建，确保 ESLint、Prettier 和静态可操作性审计通过。
- 提交并推送 `main`。
- 执行 `bash backend/scripts/deploy_to_server.sh --frontend`，只更新静态资源。
- 发布后确认首页 HTTP 200、API readyz 仍为 200，并检查线上产物包含侧栏开关标识。

## 风险控制

- 使用 `v-show`/可访问性属性隐藏内容，不销毁节点树和右侧表单状态。
- 不触碰 API 容器，避免再次产生容器替换期间的 502。
- 不复用 Workbench 的状态，避免独立页和内嵌页之间产生隐式耦合。
