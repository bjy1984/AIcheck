import type { ProjectTreePayload } from '@/api/aicheck'

// Presentation-only mirror; parity with the backend registry is checked in tests.
export const workstationNavigation = [
  {
    id: 'A',
    name: '焊接與熱處理',
    nodeIds: [24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34]
  },
  {
    id: 'B',
    name: '設計與技術基準',
    nodeIds: [1, 4, 5, 6, 7, 8, 9, 10, 63]
  },
  {
    id: 'C',
    name: '施工組織與品質體系',
    nodeIds: [2, 11, 69]
  },
  {
    id: 'D',
    name: '材料與管道元件',
    nodeIds: [12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
  },
  {
    id: 'E',
    name: '無損檢測',
    nodeIds: [3, 35, 36, 37, 38, 39, 40, 41, 42, 65]
  },
  {
    id: 'F',
    name: '防腐、保溫與電氣保護',
    nodeIds: [43, 44, 45, 46, 47, 50]
  },
  {
    id: 'G',
    name: '安裝與現場製作',
    nodeIds: [48, 49, 51, 52, 53, 54, 55]
  },
  {
    id: 'H',
    name: '安全附件',
    nodeIds: [56, 57, 58]
  },
  {
    id: 'I',
    name: '系統試驗與吹掃清洗',
    nodeIds: [59, 60, 61, 62, 64, 66, 67, 68]
  }
]

export const filterWorkstationNodes = (
  groups: ProjectTreePayload['groups'],
  stationId: string,
  status: string
) => {
  const station = workstationNavigation.find((item) => item.id === stationId)
  return groups
    .map((group) => ({
      ...group,
      nodes: group.nodes.filter(
        (node) =>
          (!station || station.nodeIds.includes(node.nodeId)) &&
          (!status ||
            (status === 'handoff_requires_revalidation'
              ? node.handoffRevalidation === 'requires_revalidation'
              : status === 'handoff_unavailable'
                ? node.handoffRevalidation === 'unavailable'
                : node.status === status))
      )
    }))
    .filter((group) => group.nodes.length)
}

export const workstationCounts = (groups: ProjectTreePayload['groups'], stationId: string) => {
  const nodes = filterWorkstationNodes(groups, stationId, '').flatMap((group) => group.nodes)
  return {
    total: nodes.length,
    review: nodes.filter((node) => ['待审查', '复审中'].includes(node.status)).length,
    confirm: nodes.filter((node) => node.status === '待人工确认').length,
    correction: nodes.filter((node) => ['需补正', '补正中'].includes(node.status)).length
  }
}
