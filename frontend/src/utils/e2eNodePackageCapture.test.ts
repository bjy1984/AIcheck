import assert from 'node:assert/strict'
import {
  isExactNodePackageResponse,
  isIgnoredFixtureMetadata,
  nodePackagePath
} from '../../e2e/projectRegistrationUploadReviewHelpers'

assert.equal(
  nodePackagePath('P/with spaces', 36),
  '/api/projects/P%2Fwith%20spaces/nodes/36/package'
)
assert.equal(
  isExactNodePackageResponse(
    'http://127.0.0.1:8000/api/projects/P%2Fwith%20spaces/nodes/36/package',
    'P/with spaces',
    36
  ),
  true
)
assert.equal(
  isExactNodePackageResponse(
    'http://127.0.0.1:8000/api/projects/P%2Fwith%20spaces/nodes/35/package',
    'P/with spaces',
    36
  ),
  false
)

assert.equal(isIgnoredFixtureMetadata('.DS_Store'), true)
assert.equal(isIgnoredFixtureMetadata('nested/.DS_Store'), true)
assert.equal(isIgnoredFixtureMetadata('.fixture-notes'), false)
assert.equal(isIgnoredFixtureMetadata('nested/Thumbs.db'), false)
assert.equal(
  isExactNodePackageResponse(
    'http://127.0.0.1:8000/api/projects/OTHER/nodes/36/package',
    'P/with spaces',
    36
  ),
  false
)
