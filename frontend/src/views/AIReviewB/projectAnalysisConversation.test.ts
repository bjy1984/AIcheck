import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import type { ReviewBMessage, ReviewBProjectAnalysisResult } from '@/types/ai-review-b'
import type { EvidenceLink } from '@/types/aicheck'
import {
  mergeProjectAnalysisResultsIntoConversation,
  projectAnalysisResultTagType,
  resolveProjectAnalysisEvidenceLink
} from './projectAnalysisConversation'

const messages: ReviewBMessage[] = [
  {
    id: 'RMSG-1',
    sessionId: 'RSESSION-1',
    sequence: 1,
    role: 'assistant',
    messageType: 'review_response',
    status: 'completed',
    contentBlocks: [{ type: 'text', text: '节点复核历史回答' }],
    createdAt: '2026-08-27 20:05:00'
  }
]

const results: ReviewBProjectAnalysisResult[] = [
  {
    reviewRunId: 'RRUN-PA-NEW',
    projectAnalysisRunId: 'PARUN-NEW',
    status: 'waiting_human_review',
    reviewResult: 'partially_supported',
    findingDrafts: [{ id: 'FND-1', title: '许可范围需要确认' }],
    createdAt: '2026-08-27 20:00:00',
    finishedAt: '2026-08-27 20:10:00'
  },
  {
    reviewRunId: 'RRUN-PA-OLD',
    projectAnalysisRunId: 'PARUN-OLD',
    status: 'waiting_human_review',
    reviewResult: 'supported',
    findingDrafts: [],
    createdAt: '2026-08-27 18:50:00',
    finishedAt: '2026-08-27 19:00:00'
  }
]

const merged = mergeProjectAnalysisResultsIntoConversation(messages, results, 'RSESSION-1', 1)

assert.deepEqual(
  merged.map((item) => item.id),
  ['project-analysis:PARUN-OLD:1', 'RMSG-1', 'project-analysis:PARUN-NEW:1']
)
assert.equal(merged[0].role, 'assistant')
assert.equal(merged[0].messageType, 'project_analysis_result')
assert.equal(merged[0].reviewRunId, 'RRUN-PA-OLD')
assert.equal(merged[0].contentBlocks[0].type, 'project_analysis_result')
assert.deepEqual(
  (merged[0].contentBlocks[0] as { result: ReviewBProjectAnalysisResult }).result,
  results[1]
)
assert.deepEqual(
  messages.map((item) => item.id),
  ['RMSG-1'],
  '不得修改真实会话消息'
)

const realMessagesWithNonChronologicalTimes: ReviewBMessage[] = [
  { ...messages[0], id: 'RMSG-SEQUENCE-1', sequence: 1, createdAt: '2026-08-27 21:00:00' },
  { ...messages[0], id: 'RMSG-SEQUENCE-2', sequence: 2, createdAt: '2026-08-27 20:00:00' }
]
const sameSecondResult: ReviewBProjectAnalysisResult = {
  ...results[0],
  projectAnalysisRunId: 'PARUN-SAME-SECOND',
  reviewRunId: 'RRUN-PA-SAME-SECOND',
  finishedAt: '2026-08-27 21:00:00'
}
const mergedNonChronological = mergeProjectAnalysisResultsIntoConversation(
  realMessagesWithNonChronologicalTimes,
  [results[0], sameSecondResult],
  'RSESSION-1',
  1
)
assert.deepEqual(
  mergedNonChronological
    .filter((item) => item.messageType !== 'project_analysis_result')
    .map((item) => item.id),
  ['RMSG-SEQUENCE-1', 'RMSG-SEQUENCE-2'],
  '合成结果不得重排真实会话的 sequence 顺序'
)

assert.equal(projectAnalysisResultTagType('supported'), 'success')
assert.equal(projectAnalysisResultTagType('partially_supported'), 'warning')
assert.equal(projectAnalysisResultTagType('conflict'), 'danger')
assert.equal(projectAnalysisResultTagType('mismatch'), 'danger')
assert.equal(projectAnalysisResultTagType('insufficient_evidence'), 'info')

const evidenceLinks: EvidenceLink[] = [
  {
    id: 'EV-1',
    documentId: 'DOC-1',
    documentVersionId: 'DV-1',
    fileName: '许可证.pdf',
    pageNo: 1,
    quotedText: '第一页证据原文'
  },
  {
    id: 'EV-2',
    documentId: 'DOC-1',
    documentVersionId: 'DV-1',
    fileName: '许可证.pdf',
    pageNo: 2,
    quotedText: '第二页证据原文'
  }
]
assert.equal(
  resolveProjectAnalysisEvidenceLink(
    {
      fileId: 'DOC-1',
      documentVersionId: 'DV-1',
      pageNo: 2,
      quotedText: '第二页证据原文'
    },
    evidenceLinks
  )?.id,
  'EV-2'
)
assert.equal(
  resolveProjectAnalysisEvidenceLink({ fileId: 'DOC-1', documentVersionId: 'DV-1' }, evidenceLinks),
  undefined,
  '无法唯一定位时不得打开任意一条证据'
)
assert.equal(
  resolveProjectAnalysisEvidenceLink({ evidenceLinkId: 'EV-1' }, evidenceLinks)?.id,
  'EV-1'
)

const componentSource = readFileSync(
  new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url),
  'utf-8'
)
assert.match(componentSource, /证据依据/)
assert.match(componentSource, /规则依据/)
assert.match(componentSource, /projectAnalysisEvidenceLink\(evidence\)/)
assert.match(componentSource, /openEvidence\(projectAnalysisEvidenceLink\(evidence\)!\)/)

/* 幂等：把合并输出再喂回去，不产生重复卡片。
   正常渲染是 computed 不会触发，但乐观更新/快照回放一旦把合并结果
   回写 messages，重复会静默出现——实测修复前 2 条变 3 条。 */
{
  const once = mergeProjectAnalysisResultsIntoConversation(messages, results, 'RSESSION-1', 1)
  const twice = mergeProjectAnalysisResultsIntoConversation(once, results, 'RSESSION-1', 1)
  assert.deepEqual(
    twice.map((item) => item.id),
    once.map((item) => item.id),
    '二次合并产生了重复的分析卡片'
  )
}
