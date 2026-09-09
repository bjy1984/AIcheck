import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const workbenchSource = readFileSync(
  resolve(currentDir, 'ConversationalReviewWorkbenchB.vue'),
  'utf8'
)
const locatorDialogSource = readFileSync(
  resolve(currentDir, '../AICheck/components/EvidenceLocatorDialog.vue'),
  'utf8'
)

assert.match(workbenchSource, /<strong>压力管道监检工作台<\/strong>/)
assert.doesNotMatch(workbenchSource, /AI 工程监检复核工作台/)
assert.match(locatorDialogSource, /:is="inline \? 'section' : ElDialog"/)
assert.match(locatorDialogSource, /v-model="visible"/)
assert.match(locatorDialogSource, /'1040px'/)
assert.match(locatorDialogSource, /:append-to-body="!inline"/)
