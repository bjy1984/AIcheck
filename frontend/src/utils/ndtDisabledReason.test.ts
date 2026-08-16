/**
 * 禁用一个按钮而不说原因，等于让用户和界面互相沉默。
 *
 * ## 线上实测（2026-08-16，NDT 工作台）
 *
 * 三行文件，状态各不相同，「提交审批」却一律灰着、**一个字的理由都没有**：
 *
 *     1  射线检测报告.pdf              上传中     · 草稿
 *     2  射线检测报告-实操审计.pdf     识别失败   · 草稿
 *     3  B00…基础无损检测报告.docx     上传成功   · 待审查
 *
 * 三种情况该做的事完全不同——等一等 / 重新上传 / 已经提交过了——
 * 而用户看到的是同一个灰按钮，只能挨个猜，或者以为系统坏了。
 *
 * 第 3 行尤其危险：它「上传成功」，看起来完全具备提交条件，
 * 实际是**已经提交过**。不说清楚，NDT 会反复点，然后来问为什么交不上去。
 *
 * ## 判据
 *
 * 每种不可提交的成因都要给出**能指导下一步**的话，而不是「不满足条件」。
 */
import assert from 'node:assert/strict'

import { ndtEditBlockedReason, ndtSubmitBlockedReason } from './documentUploadActions'

// 可以提交时不给理由（空串 = 按钮可用）
assert.equal(ndtSubmitBlockedReason('草稿', '上传成功'), '')
assert.equal(ndtSubmitBlockedReason('需补正', '上传成功'), '')

// 上传侧的三种成因，各说各的
assert.match(ndtSubmitBlockedReason('草稿', '上传中'), /还在上传/)
assert.match(ndtSubmitBlockedReason('草稿', '识别失败'), /重新上传/)
assert.match(ndtSubmitBlockedReason('草稿', '失败重新上传'), /重新上传/)

// 审批侧：已提交 / 已通过，要说清楚「不是你操作错了」
assert.match(ndtSubmitBlockedReason('待审查', '上传成功'), /已提交审批/)
assert.match(ndtSubmitBlockedReason('已通过', '上传成功'), /已通过审查/)

// 兜底也要带上当前状态，别只说「不满足条件」
const fallback = ndtSubmitBlockedReason('未知状态', '上传成功')
assert.match(fallback, /未知状态/)
assert.match(fallback, /草稿或需补正/)

// 「调整业务规则」同理——同一个页面上两个灰按钮，不能只解释一个
assert.equal(ndtEditBlockedReason('草稿'), '')
assert.match(ndtEditBlockedReason('待审查'), /已提交审批/)
assert.match(ndtEditBlockedReason('已通过'), /已通过审查/)

// 理由必须是完整的一句话：以句号结尾，不是半截提示
for (const reason of [
  ndtSubmitBlockedReason('草稿', '上传中'),
  ndtSubmitBlockedReason('待审查', '上传成功'),
  ndtEditBlockedReason('待审查')
]) {
  assert.ok(reason.endsWith('。'), `理由要是完整一句话：${reason}`)
}

console.log('NDT disabled-reason contract passed')
