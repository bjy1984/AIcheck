import assert from 'node:assert/strict'

import { blockingReasonsAsItems, buildSuggestedQuestions } from './suggestedQuestions'

// 线上节点 24（焊工资格证及持证合格项目）2026-08-13 的真实数据
const NODE_24_ITEMS = [
  {
    key: 'submission',
    label: '资料提交',
    status: 'not_started',
    summary: '仍有 4 项必传资料未匹配。'
  },
  {
    key: 'ocr',
    label: 'OCR 抽取',
    status: 'needs_attention',
    metric: '0/1 就绪',
    summary: '存在抽取不完整、产物不一致或定位框缺失。',
    issues: [{ code: 'OCR_INCOMPLETE', message: '存在抽取不完整、产物不一致或定位框缺失。' }]
  },
  {
    key: 'evidence',
    label: '证据确认',
    status: 'needs_attention',
    metric: '0/4 已确认',
    summary: '仍有必传审查点缺少已确认资料证据，不能形成满足要求类结论。',
    issues: [{ code: 'MISSING_REQUIRED_EVIDENCE', message: '仍有审查点缺少已确认资料证据。' }]
  },
  { key: 'ai_review', label: 'AI 复核', status: 'not_started' }
]

const NODE_24_BASIS = {
  inspectionItem: '焊工资格证及持证合格项目',
  ruleName: '焊工资格证及持证合格项目',
  criteria:
    '标准规范：《特种设备焊接操作人员考核细则》(TSG Z6002-2010)。监检人员需现场核对人证是否相符…',
  checkMethod:
    '工作见证： 需提供焊工的有效资格证书原件或复印件，以及证书上明确标注的“合格项目”范围（如焊接方法、母材类别、位置等）。'
}

// —— 当前卡点排最前 ——
// 监检打开这个节点，十有八九是为了处理卡住的那件事。把「了解规则」排前面，
// 等于让他先读一遍他已经知道的东西。
{
  const questions = buildSuggestedQuestions(NODE_24_ITEMS, NODE_24_BASIS)
  assert.equal(questions[0].origin, 'blocker')
  assert.ok(questions[0].text.includes('OCR'))
  assert.equal(questions[1].origin, 'blocker')
  assert.ok(questions[1].text.includes('资料或证据'))
  // 未开始 / 已完成的项不该产生问题——那不是现在要处理的事
  assert.ok(!questions.some((q) => q.text.includes('AI 复核')))
}

// 默认最多 4 条：再多就成了一堵墙，人反而不会读
assert.equal(buildSuggestedQuestions(NODE_24_ITEMS, NODE_24_BASIS).length, 4)
assert.equal(buildSuggestedQuestions(NODE_24_ITEMS, NODE_24_BASIS, 2).length, 2)
// limit 传 0 或负数时至少给一条，不给空数组——空推荐区看上去像功能坏了
assert.equal(buildSuggestedQuestions(NODE_24_ITEMS, NODE_24_BASIS, 0).length, 1)

// —— 认不出的 issue code 要兜底，不能跳过 ——
// 跳过会让「节点明明卡住了却没有相关推荐」，看上去像推荐坏了。
{
  const questions = buildSuggestedQuestions(
    [
      {
        key: 'x',
        label: '某项',
        status: 'needs_attention',
        summary: '某种没见过的问题',
        issues: [{ code: 'BRAND_NEW_CODE' }]
      }
    ],
    {}
  )
  assert.ok(questions[0].text.includes('某种没见过的问题'))
  assert.equal(questions[0].origin, 'blocker')
}

// 中英两套状态写法都要认（ai_runs 写中文、review_runs 写英文，历史遗留）
{
  const zh = buildSuggestedQuestions(
    [{ key: 'ocr', status: '需关注', issues: [{ code: 'OCR_INCOMPLETE' }] }],
    {}
  )
  assert.equal(zh[0].origin, 'blocker')
}

// —— 规则依据 ——
// criteria 动辄几百字，不能整段塞进按钮；checkMethod 要截断成一句话。
{
  const questions = buildSuggestedQuestions([], NODE_24_BASIS)
  assert.ok(questions.some((q) => q.text === '焊工资格证及持证合格项目的判定依据是什么？'))
  const byMethod = questions.find((q) => q.text.startsWith('按「'))
  assert.ok(byMethod)
  assert.ok(byMethod.text.length < 60, `按钮文案过长：${byMethod.text.length} 字`)
  // 「工作见证：」是字段前缀不是内容，不该出现在问题里
  assert.ok(!byMethod.text.includes('工作见证'))
}

// —— 没有任何数据时也要给一条 ——
// 空推荐区看上去像功能坏了；通用问题至少能让人开口。
{
  const questions = buildSuggestedQuestions(undefined, undefined)
  assert.equal(questions.length, 1)
  assert.equal(questions[0].origin, 'general')
}

// 去重：同一个问题从卡点和规则两条路各出一次时，保留先出现的（卡点优先）
{
  const dup = [
    { key: 'a', status: 'needs_attention', issues: [{ code: 'MATERIALS_MISSING' }] },
    { key: 'b', status: 'needs_attention', issues: [{ code: 'MATERIALS_MISSING' }] }
  ]
  const questions = buildSuggestedQuestions(dup, {})
  const materials = questions.filter((q) => q.text === '当前还缺哪些资料？分别影响什么审查判断？')
  assert.equal(materials.length, 1)
}

// 脏数据不能把对话框带崩——它在主链路上
assert.ok(buildSuggestedQuestions([null as never, 3 as never], undefined).length >= 1)

// —— 两个数据来源要归一 ——
// 审计项总览给 items[].issues[].code，AI 复核工作台只有 blockingReasons[].code。
// 推荐问题不该关心数据从哪来；在调用处写两套分支迟早会漏掉一边。
{
  const reasons = [
    { code: 'MISSING_REQUIRED_EVIDENCE', message: '仍有审查点缺少已确认资料证据。' },
    { code: 'MATERIALS_MISSING', message: '仍有 4 项必传资料未匹配。' }
  ]
  const questions = buildSuggestedQuestions(blockingReasonsAsItems(reasons), NODE_24_BASIS)
  assert.equal(questions[0].origin, 'blocker')
  assert.ok(questions.some((q) => q.text.includes('资料或证据')))
  assert.ok(questions.some((q) => q.text === '当前还缺哪些资料？分别影响什么审查判断？'))
}

// 没有卡点时退回规则问题，不给空
assert.ok(buildSuggestedQuestions(blockingReasonsAsItems([]), NODE_24_BASIS).length >= 2)
assert.equal(blockingReasonsAsItems(undefined).length, 0)
assert.equal(blockingReasonsAsItems([null as never]).length, 0)
