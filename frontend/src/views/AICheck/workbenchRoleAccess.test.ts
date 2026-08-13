import assert from 'node:assert/strict'

import { canLoadReportArchive, loadRoleScopedReportArchive } from './workbenchRoleAccess'

assert.equal(canLoadReportArchive('contractor'), false)
assert.equal(canLoadReportArchive('ndt'), false)
assert.equal(canLoadReportArchive('inspection'), true)
assert.equal(canLoadReportArchive('owner'), true)
assert.equal(canLoadReportArchive('admin'), true)
assert.equal(canLoadReportArchive('fde'), true)

let deniedCalls = 0
const contractorData = await loadRoleScopedReportArchive('contractor', {
  reports: async () => {
    deniedCalls += 1
    return ['forbidden-report']
  },
  archiveItems: async () => {
    deniedCalls += 1
    return ['forbidden-archive']
  }
})
assert.deepEqual(contractorData, { reports: [], archiveItems: [] })
assert.equal(deniedCalls, 0)

const inspectionData = await loadRoleScopedReportArchive('inspection', {
  reports: async () => ['report-1'],
  archiveItems: async () => ['archive-1']
})
assert.deepEqual(inspectionData, { reports: ['report-1'], archiveItems: ['archive-1'] })

console.log('workbench report/archive role access contract passed')
