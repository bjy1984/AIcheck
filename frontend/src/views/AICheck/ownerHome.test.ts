import assert from 'node:assert/strict'

import type { MessageItem, ProjectTreeNode } from '@/types/aicheck'
import {
  ownerAttentionNodes,
  ownerBucket,
  ownerFeed,
  ownerProgress,
  ownerStatusCounts
} from './ownerHome'

const node = (nodeId: number, status: string, name = `节点${nodeId}`) =>
  ({ nodeId, name, status, groupName: '', fileCount: 0 }) as unknown as ProjectTreeNode

// 四档：已通过 / 审查中 / 需补正 / 待提交；认不出的状态算待提交（还没到监检手上）
assert.equal(ownerBucket('已通过'), 'passed')
assert.equal(ownerBucket('不适用'), 'passed')
assert.equal(ownerBucket('待人工确认'), 'reviewing')
assert.equal(ownerBucket('复审中'), 'reviewing')
assert.equal(ownerBucket('补正中'), 'correction')
assert.equal(ownerBucket('部分提交'), 'pending')
assert.equal(ownerBucket('奇怪的新状态'), 'pending')

const nodes = [
  node(1, '待提交'),
  node(16, '需补正', '压力管道元件以及安全附件产品质量证明文件'),
  node(24, '待人工确认'),
  node(40, '待审查'),
  node(59, '待提交'),
  node(68, '待提交')
]
assert.deepEqual(ownerStatusCounts(nodes), {
  passed: 0,
  reviewing: 2,
  correction: 1,
  pending: 3,
  total: 6
})

assert.deepEqual(ownerProgress([{ key: 'progress', value: '32%' }]), { label: '32%', percent: 32 })
assert.deepEqual(ownerProgress([{ key: 'progress', value: 0 }]), { label: '0%', percent: 0 })

const message = (extra: Partial<MessageItem>): MessageItem =>
  ({
    id: 'M',
    title: '',
    content: '',
    read: false,
    createdAt: '2026-06-25 10:00:00',
    ...extra
  }) as MessageItem

// 需要关注：退回原因用监检退回时写的那句；没有这条消息时不编原因
const withReason = ownerAttentionNodes(nodes, [
  message({ kind: 'node_correction', nodeId: 16, content: '质量证明书缺少钢印页' })
])
assert.equal(withReason.length, 1)
assert.equal(withReason[0].reason, '监检退回：质量证明书缺少钢印页')
assert.equal(withReason[0].at, '06-25')
assert.equal(ownerAttentionNodes(nodes, [])[0].reason, '监检已退回，等施工方补正')

// 最新动态：有发给建设方的消息就用消息，按时间倒序取前三条
const feed = ownerFeed(
  [
    message({
      title: '节点 16 退回补正',
      kind: 'node_correction',
      createdAt: '2026-06-25 09:00:00'
    }),
    message({
      title: '节点 24 审查结论：满足要求',
      kind: 'node_conclusion',
      createdAt: '2026-06-26 09:00:00'
    }),
    message({
      title: '报告已归档：监督检验报告',
      kind: 'report_archived',
      createdAt: '2026-06-26 08:00:00'
    }),
    message({ title: '更早的一条', createdAt: '2026-06-01 08:00:00' })
  ],
  [],
  []
)
assert.deepEqual(
  feed.map((item) => [item.title, item.at, item.tone]),
  [
    ['节点 24 审查结论：满足要求', '06-26', 'green'],
    ['报告已归档：监督检验报告', '06-26', 'blue'],
    ['节点 16 退回补正', '06-25', 'red']
  ]
)
// 没有消息时退回到报告与归档的更新记录
assert.equal(
  ownerFeed(
    [],
    [],
    [
      {
        id: 'A',
        name: '证据定位包.zip',
        type: 'evidence',
        updatedAt: '2026-06-26 09:45:00'
      } as never
    ]
  )[0].title,
  '归档资料更新：证据定位包.zip'
)
