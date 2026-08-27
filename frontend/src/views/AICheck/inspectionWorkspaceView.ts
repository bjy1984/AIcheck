export type InspectionWorkspaceView = 'ai' | 'list'

export const resolveInspectionWorkspaceView = (value: unknown): InspectionWorkspaceView =>
  value === 'ai' ? 'ai' : 'list'
