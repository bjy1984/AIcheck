export type InspectionWorkspaceView = 'ai' | 'important' | 'list'

export const resolveInspectionWorkspaceView = (value: unknown): InspectionWorkspaceView =>
  value === 'important' ? 'important' : value === 'ai' ? 'ai' : 'list'
