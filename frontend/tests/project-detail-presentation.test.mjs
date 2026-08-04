import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatNodeScope,
  formatParticipantType,
  formatProjectRegion
} from '../src/views/AICheck/utils/projectDetailPresentation.ts'

test('renders blank project regions with a placeholder', () => {
  assert.equal(formatProjectRegion(undefined), '-')
  assert.equal(formatProjectRegion('   '), '-')
  assert.equal(formatProjectRegion('华南'), '华南')
})

test('renders participant types in Chinese and preserves unknown values', () => {
  assert.equal(formatParticipantType('owner'), '建设单位')
  assert.equal(formatParticipantType('contractor'), '施工方')
  assert.equal(formatParticipantType('ndt'), '无损检测机构')
  assert.equal(formatParticipantType('inspection'), '监检人员')
  assert.equal(formatParticipantType('custom'), 'custom')
  assert.equal(formatParticipantType(''), '-')
})

test('compacts continuous and discrete node scopes with a unique count', () => {
  assert.equal(formatNodeScope([1, 2, 3, 4, 8, 10, 11, 12]), '1–4、8、10–12（8 个节点）')
  assert.equal(formatNodeScope(Array.from({ length: 69 }, (_, index) => index + 1)), '1–69（69 个节点）')
})

test('sorts and deduplicates node scopes and ignores invalid values', () => {
  assert.equal(formatNodeScope([3, 2, 2, 1, 0, -1, Number.NaN]), '1–3（3 个节点）')
  assert.equal(formatNodeScope([]), '-')
  assert.equal(formatNodeScope(undefined), '-')
})
