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
  /** 每个节点实际落在哪个半径上（一层可能分成多圈错排）。 */
  const rowRadiusOf = new Map<string, number>()
  /** 每层的厚度：分了几圈就有 (rows-1)*rowGap 那么厚。
   *  回拉平滑必须知道它——只按基准半径判断与外层的距离，会把本层的外圈
   *  推进外层里去（0819 实测：第 1 层外圈 783 撞上第 2 层 877，差 94 < 需要的 146）。 */
  const ringThickness: number[] = []
  /** 每层与**内侧那层**之间真正需要的径向间距（按两层的实际尺寸算）。
   *  回拉平滑拿它当上限：用 MIN_RING_STEP 那个下限去判，等于允许推到
   *  比实际需求更近的位置，跨环重叠就是这么回来的。 */
  const ringStepNeeded: number[] = []
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
    /* 一层拆成几圈错排。
     *
     * 绑定约束是**周长**：138 个节点 × 约 150px 标签宽 ÷ 2π 直接把半径顶到 3000+，
     * 而角度怎么分配都改不了这个和。唯一的杠杆是分成 rows 圈——每圈只放
     * 1/rows 个节点，周长需求同比例下降。
     *
     * 行距必须按 hypot 给（见下方相邻对推导的同一条理由）：
     * 若两个框的间隔向量长度 L ≥ hypot(W, H)，则不可能同时 |dx|<W 且 |dy|<H
     * （否则 L² = dx²+dy² < W²+H² = hypot² ≤ L²，矛盾）。
     *
     * **上一版就死在这里**：当时行距写了固定 46px，而这份数据要 ~162px，
     * θ≈0 处径向≈横向，错开的量全落在 x 轴，测试抓出 89 对重叠。
     * 不是「分圈错排」这个想法错，是行距给错了。 */
    const rowGap = ringStep(ringSize, ringSize)
    const stepFromInner = ringStep(previousRingSize, ringSize)
    const radiusForRows = (rows: number) => {
      let base = Math.max(previousRadius + stepFromInner, needed / rows / (2 * Math.PI))
      // 同圈相邻的是隔 rows 个的那两个，角间隔相应放大
      for (let i = rows; i < members.length; i += 1) {
        const a = byId.get(members[i - rows])!
        const b = byId.get(members[i])!
        const gap = angleOf.get(members[i])! - angleOf.get(members[i - rows])!
        if (gap > 1e-6) {
          const w = (a.width + b.width) / 2 + RECT_GAP
          const h = (a.height + b.height) / 2 + RECT_GAP
          base = Math.max(base, Math.hypot(w, h) / gap)
        }
      }
      return base
    }
    let rows = 1
    let radius = radiusForRows(1)
    for (let candidate = 2; candidate <= 4 && members.length > candidate; candidate++) {
      const base = radiusForRows(candidate)
      // 比的是这一层的**最外沿**：圈数多了内圈小，但整体厚度会增加
      if (base + (candidate - 1) * rowGap < radius + (rows - 1) * rowGap) {
        rows = candidate
        radius = base
      }
    }
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
    for (let i = rows; i < members.length; i++) {
      const a = byId.get(members[i - rows])!
      const b = byId.get(members[i])!
      const gap = angleOf.get(members[i])! - angleOf.get(members[i - rows])!
      if (gap > 1e-6) {
        const w = (a.width + b.width) / 2 + RECT_GAP
        const h = (a.height + b.height) / 2 + RECT_GAP
        radius = Math.max(radius, Math.hypot(w, h) / gap)
      }
    }
    // 首尾也是相邻（圆是闭合的）——漏掉的话 θ=0 两侧的两个框会叠
    if (members.length > rows) {
      const a = byId.get(members[members.length - rows])!
      const b = byId.get(members[0])!
      const gap =
        Math.PI * 2 - (angleOf.get(members[members.length - rows])! - angleOf.get(members[0])!)
      if (gap > 1e-6) {
        const w = (a.width + b.width) / 2 + RECT_GAP
        const h = (a.height + b.height) / 2 + RECT_GAP
        radius = Math.max(radius, Math.hypot(w, h) / gap)
      }
    }
    members.forEach((id, index) => {
      const angle = angleOf.get(id)!
      // 依角序轮流落到各圈：相邻两个必然不同圈，靠径向的 rowGap 隔开
      const memberRadius = radius + (index % rows) * rowGap
      positions.set(id, {
        x: memberRadius * Math.cos(angle),
        y: memberRadius * Math.sin(angle)
      })
      rowRadiusOf.set(id, memberRadius)
    })
    // 下一层要从本层**最外沿**起算，否则内外层会咬在一起
    previousRadius = radius + (rows - 1) * rowGap
    previousRingSize = ringSize
    ringRadii.push(radius)
    ringThickness.push((rows - 1) * rowGap)
    ringStepNeeded.push(stepFromInner)
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
    // 上限要扣掉本层自己的厚度：本层最外圈才是真正会撞上外层的那一圈
    const ceiling =
      outer - (ringStepNeeded[depth] ?? MIN_RING_STEP) - (ringThickness[depth - 1] ?? 0)
    const pulled = Math.min(Math.max(current, proportional), ceiling)
    if (pulled > current) {
      const delta = pulled - current
      ringRadii[depth - 1] = pulled
      for (const id of rings.get(depth) || []) {
        const angle = angleOf.get(id)!
        // 整层一起外移同一个量：同层内部的分圈错排（rowGap）必须保持原样，
        // 全部压到同一半径会把错排抹掉，重叠立刻回来。
        const moved = (rowRadiusOf.get(id) ?? current) + delta
        rowRadiusOf.set(id, moved)
        positions.set(id, { x: moved * Math.cos(angle), y: moved * Math.sin(angle) })
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

/* ==========================================================================
 * 试过但**实测更差**的两条路，写在这里免得下一个人再走一遍
 * ==========================================================================
 *
 * 1. balloon（层次气泡）：每个父节点把孩子摆在自己周围的小圆上。
 *    想法是「拥挤只影响那一支、不传染全图」，实现完拿线上 259 个节点一测：
 *    包围盒 8465x8404、填充率 0.7%，比同心环的 6623x6561 / 1.2% **还差**。
 *    原因是把子树外接成圆本身就浪费（圆比它的包围盒大 ~40%），
 *    而根节点的 18 个大圆盘会把距离顶得更远。
 *
 * 2. 交叉最小化（Sugiyama 那一类的重心排序）：先量了再说——这份数据
 *    294 条边**交叉数为 0**，非树边的角跨度中位数只有 3°。没有交叉可减。
 *
 * 真正起作用的是同一层分多圈错排（见上方 radiusForRows）：绑定约束是周长，
 * 而周长需求 = Σ标签宽 / 2π，角度怎么分配都改不了这个和，只能靠分圈摊薄。
 */
