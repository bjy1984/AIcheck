/**
 * 径向分层布局的几何契约。
 *
 * ## 为什么这些性质要用测试钉住
 *
 * 「知识图谱根本没法看」的根源是力导向把层级数据揉成一坨。换成确定性
 * radial 后，可读性靠的就是下面这几条几何性质——它们不成立，图就会
 * 悄悄退回没法看的状态，而且**没有任何报错**：布局函数照样返回一堆坐标。
 *
 * 这次线上登录态不可用、无法截图验收，测试就是唯一的判据来源，
 * 所以按「真实规模」造数据（200+ 节点），不是三五个节点意思一下。
 */
import assert from 'node:assert/strict'

import {
  RECT_GAP,
  radialLayout,
  rectanglesOverlap,
  type LayoutEdge,
  type LayoutNode
} from './knowledgeGraphLayout'

/** 造一棵接近线上真实形状的层级：1 个业务包 → 16 模块 → 每模块若干节点 → 条款。 */
const buildFixture = () => {
  const nodes: LayoutNode[] = [{ id: 'root', width: 120, height: 34 }]
  const edges: LayoutEdge[] = []
  for (let m = 0; m < 16; m++) {
    const moduleId = `module-${m}`
    nodes.push({ id: moduleId, width: 110, height: 30 })
    edges.push({ source: 'root', target: moduleId })
    for (let r = 0; r < 4; r++) {
      const ruleId = `rule-${m}-${r}`
      // 宽度混合长短名——真实数据里「监检业务判断规则」和「阀门」并存
      nodes.push({ id: ruleId, width: r % 2 ? 150 : 90, height: 40 })
      edges.push({ source: moduleId, target: ruleId })
      for (let c = 0; c < 2; c++) {
        const clauseId = `clause-${m}-${r}-${c}`
        nodes.push({ id: clauseId, width: 100, height: 46 })
        edges.push({ source: ruleId, target: clauseId })
      }
    }
  }
  // 少量交叉边（规则引用别的模块的条款）——真实图不是纯树
  edges.push({ source: 'rule-0-0', target: 'clause-5-1-0' })
  edges.push({ source: 'rule-3-2', target: 'clause-9-0-1' })
  return { nodes, edges }
}

const { nodes, edges } = buildFixture()
const result = radialLayout(nodes, edges, 'root')

// ---- 一个不丢 ----
assert.equal(result.positions.size, nodes.length, '有节点没拿到坐标——它在图上会消失')

// ---- 根在中心，层级半径单调向外 ----
{
  const root = result.positions.get('root')!
  assert.deepEqual([root.x, root.y], [0, 0], '根不在中心')
  const radiusOf = (id: string) => {
    const p = result.positions.get(id)!
    return Math.hypot(p.x, p.y)
  }
  // 同一条链上，孩子必须比父亲更靠外——层级感全靠这一条
  assert.ok(radiusOf('module-3') > 0, '模块贴在根上')
  assert.ok(radiusOf('rule-3-1') > radiusOf('module-3'), '规则没有比它的模块更靠外，层级看不出来')
  assert.ok(radiusOf('clause-3-1-0') > radiusOf('rule-3-1'), '条款没有比规则更靠外')
  // 环半径列表单调递增（允许多排交错，但环与环不能倒挂）
  for (let i = 1; i < result.ringRadii.length; i++) {
    assert.ok(result.ringRadii[i] > result.ringRadii[i - 1], `第 ${i} 环半径没有比内环大`)
  }
}

// ---- 矩形零重叠：这正是力导向做不到、才换布局的那件事 ----
{
  const boxes = nodes.map((node) => ({
    ...result.positions.get(node.id)!,
    width: node.width,
    height: node.height
  }))
  const overlaps: string[] = []
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      if (rectanglesOverlap(boxes[i], boxes[j])) {
        overlaps.push(`${nodes[i].id} × ${nodes[j].id}`)
      }
    }
  }
  assert.deepEqual(overlaps, [], `矩形重叠：${overlaps.slice(0, 5).join('; ')}`)
}

// ---- 确定性：同样输入两次结果一字不差 ----
{
  const again = radialLayout(nodes, edges, 'root')
  for (const [id, p] of result.positions) {
    const q = again.positions.get(id)!
    assert.ok(p.x === q.x && p.y === q.y, `${id} 两次布局坐标不同——图每次打开长得不一样`)
  }
}

// ---- 树边被标出来：渲染端靠它把骨架画实、交叉边画淡 ----
{
  assert.ok(result.treeEdgeKeys.has('root->module-0'), '树边没标出来')
  // 交叉边不该混进树骨架
  assert.ok(
    !result.treeEdgeKeys.has('rule-0-0->clause-5-1-0') ||
      !result.treeEdgeKeys.has('rule-5-1->clause-5-1-0'),
    '同一个节点有两条树边指向它——骨架成环了'
  )
}

// ---- 孤立节点不许丢：配置有问题的部分恰恰最需要被看见 ----
{
  const withOrphan = radialLayout(
    [...nodes, { id: 'orphan-1', width: 100, height: 30 }],
    edges,
    'root'
  )
  const orphan = withOrphan.positions.get('orphan-1')
  assert.ok(orphan, '孤立节点被丢掉了——「画不出来」的数据没人会发现有问题')
  const orphanRadius = Math.hypot(orphan.x, orphan.y)
  const maxRing = Math.max(...withOrphan.ringRadii)
  assert.ok(orphanRadius >= maxRing - 1, '孤立节点混进了正常层级里，会被误读成有归属')
}

/* ---- 跨环同角度的宽框不重叠 ----
 *
 * 线上第一版叠起来的形状之一：固定环距 150px，而单链父子（同角度）
 * 各是 160px 宽的框，θ≈0 处径向≈横向，150 < (160+160)/2+gap。
 * 环距必须按两环矩形的实际尺寸算。 */
{
  const chain = radialLayout(
    [
      { id: 'r', width: 160, height: 26 },
      { id: 'a', width: 160, height: 26 },
      { id: 'b', width: 160, height: 26 }
    ],
    [
      { source: 'r', target: 'a' },
      { source: 'a', target: 'b' }
    ],
    'r'
  )
  const boxes = ['r', 'a', 'b'].map((id, i) => ({
    ...chain.positions.get(id)!,
    width: 160,
    height: 26,
    id
  }))
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      assert.ok(
        !rectanglesOverlap(boxes[i], boxes[j]),
        `跨环同角度重叠：${boxes[i].id} × ${boxes[j].id}`
      )
    }
  }
}

/* ---- 孤立节点环自己也不许重叠 ----
 *
 * 线上第一版叠起来的形状之二：孤立环只均匀撒角度、没做间距约束，
 * 两个以上孤立节点就可能叠——而孤立数据恰恰是最需要被看清的。 */
{
  const orphanNodes = Array.from({ length: 12 }, (_, i) => ({
    id: `iso-${i}`,
    width: 140,
    height: 26
  }))
  const withOrphans = radialLayout([...nodes, ...orphanNodes], edges, 'root')
  const boxes = orphanNodes.map((node) => ({
    ...withOrphans.positions.get(node.id)!,
    width: node.width,
    height: node.height,
    id: node.id
  }))
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      assert.ok(
        !rectanglesOverlap(boxes[i], boxes[j]),
        `孤立环重叠：${boxes[i].id} × ${boxes[j].id}`
      )
    }
  }
}

// ---- 空输入不炸 ----
assert.equal(radialLayout([], [], undefined).positions.size, 0)

// ---- 指向不存在节点的边被忽略而不是炸掉 ----
{
  const dirty = radialLayout(nodes, [...edges, { source: 'root', target: 'ghost' }], 'root')
  assert.equal(dirty.positions.size, nodes.length)
}

// gap 常量要为正——0 的话框贴框，看着仍像连成一片
assert.ok(RECT_GAP > 0)

console.log('Knowledge graph radial layout contract passed')
