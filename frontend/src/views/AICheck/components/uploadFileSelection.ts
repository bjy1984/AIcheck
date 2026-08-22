import type { UploadFile } from 'element-plus'

export type UploadFileIdentity = Pick<File, 'name' | 'size' | 'lastModified'>

export const rawFilesFromUploadList = (uploadFiles: UploadFile[]): File[] =>
  uploadFiles.flatMap((item) => (item.raw ? [item.raw] : []))

const uploadFileIdentityKey = (file: UploadFileIdentity): string =>
  `${file.name}:${file.size}:${file.lastModified}`

export const removeUploadFileByIdentity = (
  uploadFiles: readonly UploadFile[],
  target: UploadFileIdentity
): UploadFile[] =>
  uploadFiles.filter(
    (uploadFile) =>
      !uploadFile.raw || uploadFileIdentityKey(uploadFile.raw) !== uploadFileIdentityKey(target)
  )

export const acceptedUploadFilesFromList = (uploadFiles: readonly UploadFile[]): UploadFile[] =>
  uploadFiles.filter((uploadFile) => !uploadFile.raw || isAcceptedUploadFile(uploadFile.raw.name))

export const appendUniqueUploadFiles = <T extends UploadFileIdentity>(
  existing: readonly T[],
  incoming: readonly T[]
): T[] => {
  const seen = new Set(existing.map(uploadFileIdentityKey))
  return [
    ...existing,
    ...incoming.filter((file) => {
      const key = uploadFileIdentityKey(file)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  ]
}

export const canSubmitInlineUpload = (
  files: readonly UploadFileIdentity[],
  loading: boolean
): boolean => files.length > 0 && !loading

const acceptedExtensions = new Set([
  'pdf',
  'doc',
  'docx',
  'xls',
  'xlsx',
  'jpg',
  'jpeg',
  'png',
  'zip'
])

export const isAcceptedUploadFile = (fileName: string): boolean => {
  const extension = fileName.split('.').pop()?.toLowerCase() || ''
  return acceptedExtensions.has(extension)
}
