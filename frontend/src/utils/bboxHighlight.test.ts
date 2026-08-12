import assert from 'node:assert/strict'

import { bboxToPercentStyle, normalizeBbox } from './bboxHighlight'

// —— normalizeBbox ——
assert.deepEqual(normalizeBbox([10, 20, 110, 70]), [10, 20, 110, 70])
// 后端 JSON 里出现过字符串坐标
assert.deepEqual(normalizeBbox(['10', '20', '110', '70'] as unknown as number[]), [10, 20, 110, 70])

// 零宽/反向框画出来要么是空的、要么是翻转的，两种都比不画更糟
assert.equal(normalizeBbox([100, 20, 100, 70]), undefined)
assert.equal(normalizeBbox([110, 20, 10, 70]), undefined)
assert.equal(normalizeBbox([10, 70, 110, 20]), undefined)

assert.equal(normalizeBbox(undefined), undefined)
assert.equal(normalizeBbox(null), undefined)
assert.equal(normalizeBbox([10, 20, 110]), undefined)
assert.equal(normalizeBbox([10, 20, Number.NaN, 70]), undefined)

// —— bboxToPercentStyle ——
assert.deepEqual(bboxToPercentStyle([100, 50, 300, 150], { width: 1000, height: 500 }), {
  left: '10%',
  top: '10%',
  width: '20%',
  height: '20%'
})

// 用百分比而非像素，是为了让高亮跟随 <img> 等比缩放：
// 同一个 bbox，无论 <img> 被渲染成多大，百分比都不变
assert.deepEqual(bboxToPercentStyle([0, 0, 500, 250], { width: 1000, height: 500 }), {
  left: '0%',
  top: '0%',
  width: '50%',
  height: '50%'
})

// 原图尺寸未知时宁可不画，也不画错位的框
assert.equal(bboxToPercentStyle([10, 20, 110, 70], null), null)
assert.equal(bboxToPercentStyle([10, 20, 110, 70], { width: 0, height: 500 }), null)

// bbox 非法时返回 null，调用方据此退化为「只跳页、不画框」
assert.equal(bboxToPercentStyle(undefined, { width: 1000, height: 500 }), null)
assert.equal(bboxToPercentStyle([110, 20, 10, 70], { width: 1000, height: 500 }), null)
