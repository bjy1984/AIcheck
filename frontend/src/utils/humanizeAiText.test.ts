import assert from 'node:assert/strict'

import { humanizeAiText } from './humanizeAiText'

// 生产里漏出来的那一句
assert.equal(
  humanizeAiText(
    'certificateVerification.result为evidence_insufficient；证书TS1844168-2027的持证主体、发证机关、有效期起止均未提取，且valid_until_present检查未通过。依据要求，证据不足的证书只能要求人工确认，不能判为满足。'
  ),
  '服务端证照核验结论为证据不足；证书TS1844168-2027的持证主体、发证机关、有效期起止均未提取，且「有效期截止日期已识别」检查未通过。依据要求，证据不足的证书只能要求人工确认，不能判为满足。'
)

// 长的先匹配：带点的写法不能被短的 certificateVerification 抢先
assert.equal(
  humanizeAiText('certificateVerification.result 是 failed'),
  '服务端证照核验结论 是 未通过'
)
assert.equal(humanizeAiText('certificateVerification 通过'), '服务端证照核验 通过')

// 失败原因和提示码
assert.equal(
  humanizeAiText('原因：certificate_expires_before_period_end'),
  '原因：证书在施工结束前到期'
)
assert.equal(
  humanizeAiText('construction_period_missing_using_reference_date'),
  '未填写施工起止日期，按核验日期判断'
)

// 只替换完整的名词：别的单词里含有它们的不动
assert.equal(humanizeAiText('failed_over 与 supported_by 不动'), 'failed_over 与 supported_by 不动')
assert.equal(humanizeAiText('prepassed'), 'prepassed')
assert.equal(humanizeAiText('myevidenceRefs2'), 'myevidenceRefs2')

// 紧挨着中文、标点、括号都要认
assert.equal(humanizeAiText('（evidence_insufficient）'), '（证据不足）')
assert.equal(humanizeAiText('结论为human_confirm。'), '结论为需人工确认。')

// 同一句里出现多个，也包括首尾
assert.equal(
  humanizeAiText('holder_present、scope_present 均 passed'),
  '「持证主体已识别」、「许可范围已识别」 均 通过'
)
assert.equal(humanizeAiText('failed'), '未通过')

// 认不出的、普通中文、空值：原样
assert.equal(humanizeAiText('钢管规格108×8.0需人工复核'), '钢管规格108×8.0需人工复核')
assert.equal(humanizeAiText('some_unknown_code'), 'some_unknown_code')
assert.equal(humanizeAiText(''), '')
assert.equal(humanizeAiText(undefined), '')
assert.equal(humanizeAiText(null), '')
assert.equal(humanizeAiText(42), '42')
