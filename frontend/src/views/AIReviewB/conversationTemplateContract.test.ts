import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 对话流模板契约：分析卡片按时间插入的最后一环。
 *
 * merge 层的顺序与幂等由 projectAnalysisConversation.test.ts 钉死，
 * 服务端三条约束由生产 E2E 钉死；这里钉「模板确实渲染合并后的
 * conversationMessages 且中途没人重排」——改名、二次 sort、换数据源
 * 任何一样都会让这条红。
 */
const source = readFileSync(
  join(import.meta.dirname, 'ConversationalReviewWorkbenchB.vue'),
  'utf-8'
)

// 1. computed 管道存在：merge(messages, projectAnalysisResults, ...) → conversationMessages
assert.match(
  source,
  /const conversationMessages = computed\(\(\) =>\s*\n?\s*mergeProjectAnalysisResultsIntoConversation\(/
)
assert.match(source, /workspace\.value\?\.projectAnalysisResults \|\| \[\]/)

// 2. 模板迭代的是合并结果本身
assert.match(source, /v-for="message in conversationMessages"/)

// 3. 合并结果没有被二次重排/切片后再渲染
assert.ok(
  !/conversationMessages(\.value)?\s*\.\s*(sort|reverse|toSorted|toReversed)\(/.test(source),
  '模板/脚本对 conversationMessages 做了重排——按时间插入的约束会被静默破坏'
)

console.log('对话流模板契约：通过')
