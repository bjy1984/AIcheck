import type { RoleCode } from '@/types/aicheck'

export const canLoadReportArchive = (role: RoleCode): boolean =>
  role !== 'contractor' && role !== 'ndt'

export const loadRoleScopedReportArchive = async <TReport, TArchiveItem>(
  role: RoleCode,
  loaders: {
    reports: () => Promise<TReport[]>
    archiveItems: () => Promise<TArchiveItem[]>
  }
): Promise<{ reports: TReport[]; archiveItems: TArchiveItem[] }> => {
  if (!canLoadReportArchive(role)) return { reports: [], archiveItems: [] }
  const [reports, archiveItems] = await Promise.all([loaders.reports(), loaders.archiveItems()])
  return { reports, archiveItems }
}
