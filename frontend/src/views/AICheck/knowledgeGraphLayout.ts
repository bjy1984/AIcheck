/**
 * 知识网络的**确定性径向分层布局**。
 *
 * ## 为什么放弃力导向
 *
 * 这份数据本质是层级：业务包 → 业务模块 → 监检节点/规则 → 条款/资料。
 * 力导向把节点当无差别的质点，把层级揉成中心一坨互相挤压的矩形——
 * 用户的原话是「知识图谱根本没法看」。**布局要顺着数据的形状来**：
 * hub-and-spoke 的层级数据就该一环一环摊开，中心是业务包，
 * 越往外越细，一眼能看出「谁属于谁」。
 *
 * 换成确定性布局还顺带解决了力导向的整类老毛病：
 * - 布局不再持续漂移（之前「定位对不准」「截图判据被动画污染」都源于此）
 * - 每次打开长得一样，用户不用重新找方位
 * - 不需要「跑完再按矩形分离」的两段式补丁
 *
 * ## 几个几何事实（不要试图「优化」掉）
 *
 * - 200 个宽 130px 的矩形排成一圈就是需要 ~26000px 周长。这不是浪费，
 *   是矩形面积的下限。缓解手段是**同环分成多排交错**（周长需求 ÷ 排数），
 *   不是把半径硬压小——压小只会回到互相压框的老样子。
 * - 初始视图由 ECharts 对包围盒做 fit，看的是**结构轮廓**；
 *   细节靠 roam 放大看。全图 259 个全名矩形同时可读，物理上不存在。
 */

export type LayoutNode = {
  id: string
  width: number
  height: number
}

export type LayoutEdge = { source: string; target: string }

export type LayoutResult = {
  positions: Map<string, { x: number; y: number }>
  /** BFS 生成树上的边（"source->target"）。渲染时树边画实、交叉边画淡，
      否则 294 条边全都一样重，放射结构会被横向交叉线糊掉。 */
  treeEdgeKeys: Set<string>
  /** 每一环的半径，从内到外。给测试用：环距必须单调拉开。 */
  ringRadii: number[]
}

/** 矩形之间的最小间距。0 的话框贴在一起，看着仍像连成一片。 */
export const RECT_GAP = 10

/** 相邻两环的最小径向间隔下限。真正的间隔按两环矩形的实际尺寸算——
 *  见 ringStep()：150px 的固定环距放不下两个 160px 宽的框在 θ≈0 处同角相邻，
 *  线上第一版就是这么叠起来的。 */
const MIN_RING_STEP = 90

/** 相邻两环需要的径向间隔。
 *
 * 两个框在同一角度上下环相邻时，间隔向量是径向的：θ≈0 处径向≈横向，
 * 卡的是**宽度**；θ≈π/2 处卡的是高度。hypot 同时盖住两轴（与同环
 * 相邻对的推导相同）。用两环各自的最大尺寸算——保守，但不会再叠。 */
function ringStep(
  a: { maxWidth: number; maxHeight: number },
  b: { maxWidth: number; maxHeight: number }
): number {
  const w = (a.maxWidth + b.maxWidth) / 2 + RECT_GAP
  const h = (a.maxHeight + b.maxHeight) / 2 + RECT_GAP
  return Math.max(MIN_RING_STEP, Math.hypot(w, h))
}

export function radialLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  rootId?: string
): LayoutResult {
  const positions = new Map<string, { x: number; y: number }>()
  const treeEdgeKeys = new Set<string>()
  if (!nodes.length) return { positions, treeEdgeKeys, ringRadii: [] }

  const byId = new Map(nodes.map((node) => [node.id, node]))
  const neighbors = new Map<string, string[]>()
  for (const node of nodes) neighbors.set(node.id, [])
  for (const edge of edges) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) continue
    neighbors.get(edge.source)!.push(edge.target)
    neighbors.get(edge.target)!.push(edge.source)
  }

  // 根：指定的，或度数最大的（hub-and-spoke 数据里 hub 就是根）
  const root =
    rootId && byId.has(rootId)
      ? rootId
      : [...neighbors.entries()].sort((a, b) => b[1].length - a[1].length)[0][0]

  // BFS：深度 + 生成树。首次到达者做树父——多父（交叉边）只取一条当骨架，
  // 其余仍然画出来，只是画淡。
  const depthOf = new Map<string, number>([[root, 0]])
  const childrenOf = new Map<string, string[]>()
  const queue = [root]
  while (queue.length) {
    const current = queue.shift()!
    for (const next of neighbors.get(current) || []) {
      if (depthOf.has(next)) continue
      depthOf.set(next, depthOf.get(current)! + 1)
      if (!childrenOf.has(current)) childrenOf.set(current, [])
      childrenOf.get(current)!.push(next)
      treeEdgeKeys.add(`${current}->${next}`)
      queue.push(next)
    }
  }

  /* 连不到根的节点不许丢。孤立数据往往正是配置出了问题的那部分，
     「画不出来」会让它们彻底没人发现。放到最外一环之外单独一圈。 */
  const orphans = nodes.filter((node) => !depthOf.has(node.id))

  // 叶子占比分角度：子树叶子越多，占的扇区越宽。这样每个叶子拿到的
  // 角度槽是均匀的——槽宽均匀是后面「按周长定半径」能成立的前提。
  const leafCount = new Map<string, number>()
  const countLeaves = (id: string): number => {
    const children = childrenOf.get(id) || []
    const total = children.length ? children.reduce((sum, child) => sum + countLeaves(child), 0) : 1
    leafCount.set(id, total)
    return total
  }
  countLeaves(root)

  const angleOf = new Map<string, number>()
  const assignAngles = (id: string, start: number, end: number) => {
    angleOf.set(id, (start + end) / 2)
    let cursor = start
    for (const child of childrenOf.get(id) || []) {
      const span = ((end - start) * leafCount.get(child)!) / leafCount.get(id)!
      assignAngles(child, cursor, cursor + span)
      cursor += span
    }
  }
  assignAngles(root, 0, Math.PI * 2)

  // 按环收集，定半径
  const rings = new Map<number, string[]>()
  for (const [id, depth] of depthOf) {
    if (depth === 0) continue
    if (!rings.has(depth)) rings.set(depth, [])
    rings.get(depth)!.push(id)
  }

  positions.set(root, { x: 0, y: 0 })
  const ringRadii: number[] = []
  let previousRadius = 0
  const rootNode = byId.get(root)!
  let previousRingSize = { maxWidth: rootNode.width, maxHeight: rootNode.height }
  const maxDepth = Math.max(0, ...rings.keys())
  for (let depth = 1; depth <= maxDepth; depth++) {
    const members = (rings.get(depth) || []).sort((a, b) => angleOf.get(a)! - angleOf.get(b)!)
    // 周长需求 = 所有矩形宽 + 间距。除以排数就是单排要占的弧长。
    /* 半径下限一：周长平均够放（宽度之和 / 2π）；环距按两环实际尺寸算。 */
    const needed = members.reduce((sum, id) => sum + byId.get(id)!.width + RECT_GAP, 0)
    const ringSize = {
      maxWidth: Math.max(...members.map((id) => byId.get(id)!.width)),
      maxHeight: Math.max(...members.map((id) => byId.get(id)!.height))
    }
    let radius = Math.max(
      previousRadius + ringStep(previousRingSize, ringSize),
      needed / (2 * Math.PI)
    )
    /* 半径下限二：相邻对逐一收紧，条件是 rΔθ ≥ hypot(W, H)。
     *
     * 为什么是 hypot：矩形是**轴对齐**的，圆上两点的间隔向量随角度旋转。
     * 在 θ≈0 处相邻节点上下摞，卡的是高度；在 θ≈π/2 处左右排，卡的是宽度。
     * rΔθ ≥ hypot((w₁+w₂)/2+gap, (h₁+h₂)/2+gap) 在任何角度都同时盖住两轴。
     *
     * 第一版试过「同环分多排交错」来压小半径——**在轴对齐矩形上不成立**：
     * 排偏移是径向的，θ≈0 处径向≈横向，错开的 60px 全落在 x 轴，
     * y 轴只剩 Δθ 那一点点，宽扁矩形照样叠，测试抓出 89 对。
     * 大圈就是大圈：初始 fitView 看结构轮廓，放大看细节，别硬压。 */
    for (let i = 1; i < members.length; i++) {
      const a = byId.get(members[i - 1])!
      const b = byId.get(members[i])!
      const gap = angleOf.get(members[i])! - angleOf.get(members[i - 1])!
      if (gap > 1e-6) {
        const w = (a.width + b.width) / 2 + RECT_GAP
        const h = (a.height + b.height) / 2 + RECT_GAP
        radius = Math.max(radius, Math.hypot(w, h) / gap)
      }
    }
    // 首尾也是相邻（圆是闭合的）——漏掉的话 θ=0 两侧的两个框会叠
    if (members.length > 1) {
      const a = byId.get(members[members.length - 1])!
      const b = byId.get(members[0])!
      const gap =
        Math.PI * 2 - (angleOf.get(members[members.length - 1])! - angleOf.get(members[0])!)
      if (gap > 1e-6) {
        const w = (a.width + b.width) / 2 + RECT_GAP
        const h = (a.height + b.height) / 2 + RECT_GAP
        radius = Math.max(radius, Math.hypot(w, h) / gap)
      }
    }
    members.forEach((id) => {
      const angle = angleOf.get(id)!
      positions.set(id, { x: radius * Math.cos(angle), y: radius * Math.sin(angle) })
    })
    previousRadius = radius
    previousRingSize = ringSize
    ringRadii.push(radius)
  }

  /* 回拉平滑：外环因周长约束被推得很远时，内环如果还贴着中心，
   * 中间就是一大片空——「padding 太大」的观感一半来自这里。
   * 把内环按深度比例外推（只外推、不内收，且保持与外环的最小环距），
   * 环变成近似等距的同心圆，走线也更短。只增不减，不会制造新的重叠：
   * 同环各节点半径一起变，弧长 rΔθ 只会变大。 */
  for (let depth = maxDepth - 1; depth >= 1; depth--) {
    const current = ringRadii[depth - 1]
    const outer = ringRadii[depth]
    const proportional = (outer * depth) / (depth + 1)
    const pulled = Math.min(Math.max(current, proportional), outer - MIN_RING_STEP)
    if (pulled > current) {
      ringRadii[depth - 1] = pulled
      for (const id of rings.get(depth) || []) {
        const angle = angleOf.get(id)!
        positions.set(id, { x: pulled * Math.cos(angle), y: pulled * Math.sin(angle) })
      }
    }
  }

  if (orphans.length) {
    /* 孤立环也要做间距约束。第一版只均匀撒角度——两个以上孤立节点
       就可能叠在一起，而孤立数据恰恰是最需要被看清的。 */
    const orphanSize = {
      maxWidth: Math.max(...orphans.map((node) => node.width)),
      maxHeight: Math.max(...orphans.map((node) => node.height))
    }
    const slice = (Math.PI * 2) / orphans.length
    let radius = Math.max(previousRadius + ringStep(previousRingSize, orphanSize), 200)
    for (let i = 0; i < orphans.length; i++) {
      const a = orphans[i]
      const b = orphans[(i + 1) % orphans.length]
      if (orphans.length > 1) {
        const w = (a.width + b.width) / 2 + RECT_GAP
        const h = (a.height + b.height) / 2 + RECT_GAP
        radius = Math.max(radius, Math.hypot(w, h) / slice)
      }
    }
    orphans.forEach((node, index) => {
      const angle = index * slice
      positions.set(node.id, { x: radius * Math.cos(angle), y: radius * Math.sin(angle) })
    })
    ringRadii.push(radius)
  }

  return { positions, treeEdgeKeys, ringRadii }
}

/** 两个矩形是否重叠（带间距）。给测试当判据用——判据和实现放一起，
    改实现的人才知道自己要对什么负责。 */
export function rectanglesOverlap(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number }
): boolean {
  return (
    Math.abs(a.x - b.x) < (a.width + b.width) / 2 && Math.abs(a.y - b.y) < (a.height + b.height) / 2
  )
}
