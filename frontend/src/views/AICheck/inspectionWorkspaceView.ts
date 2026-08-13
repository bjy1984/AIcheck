export type InspectionWorkspaceView = 'ai' | 'list'

export const resolveInspectionWorkspaceView = (value: unknown): InspectionWorkspaceView =>
  value === 'list' ? 'list' : 'ai'
