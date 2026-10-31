// 工作台只有两个整页视图。「AI审查」原来是第三个标签，现在是右下角的悬浮助手，不再占一个视图。
export type InspectionWorkspaceView = 'important' | 'list'

export const resolveInspectionWorkspaceView = (value: unknown): InspectionWorkspaceView =>
  value === 'important' ? 'important' : 'list'

// 旧链接和跳转（重要节点审查的结果、已下线的对话页）带的 view=ai：落在完整工作台，并自动弹出 AI 助手。
export const opensAiAssistant = (value: unknown): boolean => value === 'ai'
