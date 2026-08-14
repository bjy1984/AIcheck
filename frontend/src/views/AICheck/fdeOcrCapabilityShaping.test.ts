import assert from 'node:assert/strict'

import {
  normalizeOcrCapabilityBbox,
  ocrCapabilityRoiArea,
  ocrCapabilitySealRoiHasTextEvidence,
  stringifyOcrCapabilityText
} from './fdeOcrCapabilityShaping'

// 这批函数原先埋在 FdeConsole.vue（29,203 行）里，一条测试都没有。
// 它们算错不会报错——ROI 面积偏一点，预览框就画偏；文本取不出来，
// 印章证据判定就悄悄变成「没有」。搬出来的意义就在于终于测得着。

// —— stringifyOcrCapabilityText：OCR 引擎返回的形状五花八门 ——

// 引擎有时给字符串，有时给 {text}，有时给一串片段。取不出来就是空字符串，
// 而空字符串会让下游判定「这里没有文字」——与「有文字但没取到」是两回事。
assert.equal(stringifyOcrCapabilityText('直接是字符串'), '直接是字符串')
assert.equal(stringifyOcrCapabilityText(42), '42')
assert.equal(stringifyOcrCapabilityText(null), '')
assert.equal(stringifyOcrCapabilityText(undefined), '')

// 数组：逐项取值后换行拼接，空项要丢掉而不是留下空行
assert.equal(stringifyOcrCapabilityText(['甲', '', '乙']), '甲\n乙')

// 对象：认 text 字段
assert.equal(stringifyOcrCapabilityText({ text: '压力管道' }), '压力管道')

// 嵌套：数组里套对象
assert.equal(stringifyOcrCapabilityText([{ text: '上' }, { text: '下' }]), '上\n下')

// —— normalizeOcrCapabilityBbox：矩形与多边形两种输入 ——

assert.deepEqual(normalizeOcrCapabilityBbox([1, 2, 9, 7]), [1, 2, 9, 7])

// 四点多边形要能取到外接框
assert.deepEqual(
  normalizeOcrCapabilityBbox([
    [1, 2],
    [9, 2],
    [9, 7],
    [1, 7]
  ]),
  [1, 2, 9, 7]
)

// 不足四个数、非数组、空数组：返回 null 而不是 [0,0,0,0]。
// 后者会变成一个「面积为零但看起来合法」的框，被下游当成有效 ROI。
assert.equal(normalizeOcrCapabilityBbox([1, 2]), null)
assert.equal(normalizeOcrCapabilityBbox('不是数组'), null)
assert.equal(normalizeOcrCapabilityBbox([]), null)

// —— ocrCapabilityRoiArea：负宽负高要夹到 0 ——

assert.equal(ocrCapabilityRoiArea([0, 0, 10, 8]), 80)
// 坐标顺序颠倒时不能算出正面积——那会让一个坏框看起来比好框还大
assert.equal(ocrCapabilityRoiArea([10, 8, 0, 0]), 0)
assert.equal(ocrCapabilityRoiArea([5, 5, 5, 9]), 0)

// —— 印章文字证据：关键词命中 ——

assert.equal(ocrCapabilitySealRoiHasTextEvidence({ text: '特种设备安装改造修理许可证' }), true)
assert.equal(ocrCapabilitySealRoiHasTextEvidence({ sealName: '中石化安装有限公司' }), true)
// 空白与噪声不算证据
assert.equal(ocrCapabilitySealRoiHasTextEvidence({ text: '   ' }), false)
assert.equal(ocrCapabilitySealRoiHasTextEvidence({}), false)
