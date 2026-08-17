/**
 * 施工方资料分类：元件制造许可证属于材料证明，不属于资质证照。
 *
 * ## 用户报的问题（0817）
 *
 *     「元件制造许可证及相关证明的资料应该属于材料证明与复验的类别里」
 *
 * 它原先被写在「资质证照」里。这不只是文案错位——这份表同时是
 * **上传引导**和**自动分类**的依据，分错的表现是：
 * 施工方把许可证传上去，按类别取证的规则找不到它，判成缺项。
 * 而界面上「传了」和「传对了」长得一模一样，没人会想到是分类的问题。
 *
 * ## 根因不是少了关键词，是匹配规则
 *
 * 原实现是「首个匹配即胜」，类别按数组顺序排，「资质证照」在第一位，
 * 它的关键词里有通用的「许可证」。于是不管往材料那一类加多少关键词，
 * 「元件制造许可证」永远先被第一条吃掉。**只加词是修不好的。**
 *
 * 现在取匹配到的最长关键词所属类别——越长越具体。
 *
 * ## 后端也有一份
 *
 * backend/config/material_review_points.json 的 materialCategory。
 * 那边两条 manufacturing_license 也从「资质证照」改到了「材料验收与复验」，
 * 由 backend/tests/test_material_category_mapping.py 锁住。
 * **只改一边等于没改**——这个形态本轮已经反复出现。
 */
import assert from 'node:assert/strict'

import {
  CONTRACTOR_MATERIAL_REQUIREMENTS,
  inferMaterialCategory
} from './contractorMaterialCategories'

// ---- 用户报的那一条 ----
assert.equal(
  inferMaterialCategory('元件制造许可证.pdf'),
  '材料证明与复验',
  '元件制造许可证被分到了别的类别——规则会因此找不到它，判成缺项'
)
assert.equal(inferMaterialCategory('特种设备制造许可证-河北广浩.pdf'), '材料证明与复验')
assert.equal(inferMaterialCategory('压力管道元件制造许可证及型式试验证书'), '材料证明与复验')

// 建议资料里也要写着，否则施工方仍然按旧口径归集
const material = CONTRACTOR_MATERIAL_REQUIREMENTS.find((item) => item.category === '材料证明与复验')
assert.ok(material, '找不到材料证明与复验这一类')
assert.match(material.requiredItems, /元件制造许可证/, '建议资料里没提元件制造许可证')

// ---- 参与单位自身的资质仍留在资质证照 ----
const licence = CONTRACTOR_MATERIAL_REQUIREMENTS.find((item) => item.category === '资质证照')
assert.ok(licence)
assert.ok(
  !/元件制造许可证/.test(licence.requiredItems),
  '资质证照里还留着元件制造许可证——同一样东西写在两个类别下'
)
assert.equal(inferMaterialCategory('施工单位安装许可证.pdf'), '资质证照')
assert.equal(inferMaterialCategory('设计许可证书.pdf'), '资质证照')
assert.equal(inferMaterialCategory('无损检测机构核准证.pdf'), '资质证照')
assert.equal(inferMaterialCategory('焊工资格证-张三.pdf'), '资质证照')

/* ---- 匹配规则本身 ----
 * 这几条锁的是「最长关键词取胜」，不是某个具体文件名。
 * 换回「首个匹配即胜」的话，下面这条立刻失败。 */
{
  // 「制造许可」(4) 比「材料」(2) 长 —— 即使两类都命中，也该归到更具体的那个
  assert.equal(inferMaterialCategory('材料 制造许可 证明'), '材料证明与复验')
  // 「热处理」(3) 比「材料」(2) 长
  assert.equal(inferMaterialCategory('材料热处理报告.pdf'), '热处理资料')
}

// 通用词不该把无关文件吸走：一个纯粹的焊接记录不应落进材料类
assert.equal(inferMaterialCategory('焊缝返修记录.pdf'), '焊接资料')

// ---- 兜底 ----
assert.equal(inferMaterialCategory(''), '其他资料')
assert.equal(inferMaterialCategory('完全无法归类的东西.pdf'), '其他资料')

/* 结果必须是确定的：同一个输入两次分类不能不同。
 * 平手时若按 Set / 对象顺序取，实际会随实现细节漂移。 */
const twice = new Set(
  Array.from({ length: 5 }, () => inferMaterialCategory('元件制造许可证及材料复验报告.pdf'))
)
assert.equal(twice.size, 1, '同一个文件名分类结果不稳定')

// 关键词不能为空串——空串 includes 永远为真，会把所有文件吸到该类别
for (const item of CONTRACTOR_MATERIAL_REQUIREMENTS) {
  for (const keyword of item.keywords) {
    assert.ok(keyword.trim(), `${item.category} 有空关键词，会吞掉所有文件`)
  }
}

console.log('Contractor material category contract passed')
