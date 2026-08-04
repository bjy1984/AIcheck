const participantTypeLabels: Record<string, string> = {
  owner: '建设单位',
  contractor: '施工方',
  ndt: '无损检测机构',
  inspection: '监检人员'
}

export const formatProjectRegion = (value?: unknown) => String(value ?? '').trim() || '-'

export const formatParticipantType = (value?: unknown) => {
  const normalized = String(value ?? '').trim()
  return participantTypeLabels[normalized] || normalized || '-'
}

export const formatNodeScope = (values?: readonly number[] | null) => {
  const nodeIds = [
    ...new Set(
      (values || []).filter(
        (value): value is number => Number.isInteger(value) && Number.isFinite(value) && value > 0
      )
    )
  ].sort((left, right) => left - right)
  if (!nodeIds.length) return '-'

  const ranges: string[] = []
  let start = nodeIds[0]
  let end = nodeIds[0]
  for (const nodeId of nodeIds.slice(1)) {
    if (nodeId === end + 1) {
      end = nodeId
      continue
    }
    ranges.push(start === end ? String(start) : `${start}–${end}`)
    start = nodeId
    end = nodeId
  }
  ranges.push(start === end ? String(start) : `${start}–${end}`)
  return `${ranges.join('、')}（${nodeIds.length} 个节点）`
}
