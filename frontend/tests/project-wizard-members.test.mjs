import assert from 'node:assert/strict'
import test from 'node:test'

import { userBelongsToOrganization } from '../src/views/AICheck/utils/projectWizardMembers.ts'

test('matches a renamed organization by stable organization id', () => {
  assert.equal(
    userBelongsToOrganization(
      { orgId: 'ORG-CONTRACTOR-001', orgName: '施工单位旧名称' },
      { id: 'ORG-CONTRACTOR-001', name: '施工单位新名称' }
    ),
    true
  )
})

test('rejects another organization id even when names are equal', () => {
  assert.equal(
    userBelongsToOrganization(
      { orgId: 'ORG-CONTRACTOR-002', orgName: '同名施工单位' },
      { id: 'ORG-CONTRACTOR-001', name: '同名施工单位' }
    ),
    false
  )
})

test('falls back to trimmed organization names for legacy records', () => {
  assert.equal(
    userBelongsToOrganization(
      { orgName: ' 粤检无损检测 ' },
      { name: '粤检无损检测' }
    ),
    true
  )
})
