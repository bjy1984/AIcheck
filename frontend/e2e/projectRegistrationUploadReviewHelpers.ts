export const nodePackagePath = (projectId: string, nodeId: number) =>
  `/api/projects/${encodeURIComponent(projectId)}/nodes/${nodeId}/package`

export const isExactNodePackageResponse = (url: string, projectId: string, nodeId: number) => {
  try {
    return new URL(url).pathname === nodePackagePath(projectId, nodeId)
  } catch {
    return false
  }
}

export const isIgnoredFixtureMetadata = (relativePath: string) =>
  relativePath.split(/[\\/]/).at(-1) === '.DS_Store'
