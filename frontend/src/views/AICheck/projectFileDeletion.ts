import type { DocumentAsset, NodePackagePayload } from '@/types/aicheck'

export type ProjectFileRemoval = {
  packageData: NodePackagePayload | undefined
  removedFile: DocumentAsset | undefined
  originalIndex: number
}

export const removeProjectFileLocally = (
  packageData: NodePackagePayload | undefined,
  documentId: string
): ProjectFileRemoval => {
  if (!packageData) {
    return { packageData, removedFile: undefined, originalIndex: -1 }
  }
  const originalIndex = packageData.projectFiles.findIndex((item) => item.id === documentId)
  if (originalIndex < 0) {
    return { packageData, removedFile: undefined, originalIndex }
  }
  return {
    packageData: {
      ...packageData,
      projectFiles: packageData.projectFiles.filter((item) => item.id !== documentId)
    },
    removedFile: packageData.projectFiles[originalIndex],
    originalIndex
  }
}

export const restoreProjectFileLocally = (
  packageData: NodePackagePayload | undefined,
  removal: ProjectFileRemoval
): NodePackagePayload | undefined => {
  if (!packageData || !removal.removedFile) return packageData
  if (packageData.projectFiles.some((item) => item.id === removal.removedFile?.id)) {
    return packageData
  }
  const projectFiles = [...packageData.projectFiles]
  const restoreIndex = Math.min(Math.max(removal.originalIndex, 0), projectFiles.length)
  projectFiles.splice(restoreIndex, 0, removal.removedFile)
  return { ...packageData, projectFiles }
}
