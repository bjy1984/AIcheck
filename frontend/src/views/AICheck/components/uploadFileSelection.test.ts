import assert from 'node:assert/strict'

import {
  appendUniqueUploadFiles,
  acceptedUploadFilesFromList,
  canSubmitInlineUpload,
  isAcceptedUploadFile,
  rawFilesFromUploadList,
  removeUploadFileByIdentity
} from './uploadFileSelection'
import type { UploadFile } from 'element-plus'

type FileIdentity = Pick<File, 'name' | 'size' | 'lastModified'>

const first: FileIdentity = { name: '质量证明.pdf', size: 1024, lastModified: 1 }
const duplicate: FileIdentity = { name: '质量证明.pdf', size: 1024, lastModified: 1 }
const second: FileIdentity = { name: '焊接记录.docx', size: 2048, lastModified: 2 }

assert.deepEqual(appendUniqueUploadFiles([first], [duplicate, second]), [first, second])
assert.equal(canSubmitInlineUpload([], false), false)
assert.equal(canSubmitInlineUpload([first], true), false)
assert.equal(canSubmitInlineUpload([first], false), true)
assert.equal(isAcceptedUploadFile('材料报告.PDF'), true)
assert.equal(isAcceptedUploadFile('压缩包.zip'), true)
assert.equal(isAcceptedUploadFile('执行脚本.exe'), false)

const growingFiles = Array.from({ length: 15 }, (_, index) => {
  const file = {
    name: `施工资料-${index + 1}.pdf`,
    size: 1024 + index,
    lastModified: index + 1
  } as File
  return { file, uploadFile: { raw: file } as UploadFile }
})

const staleModelValue: File[] = []
let staleOverwriteSelection: File[] = []
let completeUploadListSelection: File[] = []

for (let index = 0; index < growingFiles.length; index += 1) {
  const currentUploadFile = growingFiles[index].uploadFile
  const growingUploadList = growingFiles.slice(0, index + 1).map((item) => item.uploadFile)

  // This is the old handler: each event only contributes the current file to a stale model.
  staleOverwriteSelection = appendUniqueUploadFiles(staleModelValue, [currentUploadFile.raw!])

  // The picker must consume Element Plus's complete, growing upload list.
  completeUploadListSelection = appendUniqueUploadFiles(
    staleModelValue,
    rawFilesFromUploadList(growingUploadList)
  )
}

assert.equal(staleOverwriteSelection.length, 1)
assert.deepEqual(
  completeUploadListSelection,
  growingFiles.map((item) => item.file)
)

const removedFile = growingFiles[0].file
const retainedFile = growingFiles[1].file
const newlySelectedFile = growingFiles[2].file
const internalUploadList = [{ raw: removedFile }, { raw: retainedFile }] as UploadFile[]
const internalAfterRemoval = removeUploadFileByIdentity(internalUploadList, removedFile)
assert.deepEqual(rawFilesFromUploadList(internalAfterRemoval), [retainedFile])
assert.deepEqual(
  appendUniqueUploadFiles(
    [retainedFile],
    rawFilesFromUploadList([...internalAfterRemoval, { raw: newlySelectedFile } as UploadFile])
  ),
  [retainedFile, newlySelectedFile]
)

assert.deepEqual(
  appendUniqueUploadFiles(
    [retainedFile],
    rawFilesFromUploadList([{ raw: retainedFile }, { raw: newlySelectedFile }] as UploadFile[])
  ),
  [retainedFile, newlySelectedFile]
)

const invalidFile = {
  name: '执行脚本.exe',
  size: 4096,
  lastModified: 99
} as File
const sanitizedUploadList = acceptedUploadFilesFromList([
  { raw: retainedFile },
  { raw: invalidFile }
] as UploadFile[])
assert.deepEqual(rawFilesFromUploadList(sanitizedUploadList), [retainedFile])

console.log('Upload file selection contract passed')
