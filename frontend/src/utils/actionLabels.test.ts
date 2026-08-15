/**
 * 动作权限码要显示中文——但认不出的码必须原样露出来。
 *
 * 角色权限矩阵原来直接摊 `project:view` 这类码给管理员看。加中文的同时
 * 有个更要紧的约束：新增动作却忘了配中文时，界面上要看得见那个码，
 * 而不是显示一个编出来的名字或者干脆藏起来——那才是真出事的地方。
 */
import assert from 'node:assert/strict'
import { actionLabel, actionLabelWithCode, knownActionCodes } from './actionLabels'

assert.equal(actionLabel('project:view'), '查看项目')
assert.equal(actionLabel('fde:vector-quality:apply'), '应用向量修正')

// 认不出就原样返回，不猜不藏
assert.equal(actionLabel('some:future:action'), 'some:future:action')
assert.equal(actionLabel(''), '')

// 带码的说明文案
assert.equal(actionLabelWithCode('review:save'), '保存复核结论（review:save）')
assert.equal(actionLabelWithCode('some:future:action'), 'some:future:action')

// 后端当前 61 个动作码应当都有中文；这条会在新增动作时红，提醒补上
assert.ok(knownActionCodes().length >= 61, `只配了 ${knownActionCodes().length} 个动作码的中文`)

// 容易看混的两个必须区分得开
assert.notEqual(actionLabel('ai:adopt'), actionLabel('ai:recheck'))

console.log('Action label contract passed')
