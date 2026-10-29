import assert from 'node:assert/strict'
import {
  measuredCountRows,
  measuredDuration,
  measuredQualitySections,
  measuredScore,
  taskStatusRows
} from './fdeVisualData'

assert.equal(measuredDuration({}), null, 'missing timing is not an 80ms execution')
assert.equal(measuredDuration({ durationMs: 0, latencyMs: 90 }), 0, 'a measured zero is retained')
assert.equal(measuredDuration({ durationMs: null, latencyMs: 90 }), 90)
assert.equal(measuredScore(undefined), null)
assert.equal(measuredScore(0), 0)
assert.equal(measuredScore(0.9, 'ratio'), 90)
assert.deepEqual(
  measuredQualitySections([]),
  [],
  'missing quality dimensions do not invent proxy scores'
)
assert.deepEqual(measuredQualitySections([{ key: 'retrieval' }])[0], {
  key: 'retrieval',
  name: 'retrieval',
  score: null,
  maxScore: null,
  status: 'unknown',
  blockers: []
})
assert.deepEqual(
  measuredCountRows([{ flag: 'A', count: 2 }, { flag: 'B', count: 7 }, { flag: 'C' }], 'flag'),
  [
    { key: 'B', count: 7 },
    { key: 'A', count: 2 }
  ]
)
const tasks = taskStatusRows({ aiRun: { completed: 2, failed: 1 }, reviewRun: {} })
assert.equal(tasks[0].total, 3)
assert.equal(tasks[1].available, true)
assert.equal(tasks[1].total, 0)
assert.equal(
  tasks[2].available,
  false,
  'unreported domain remains distinct from a measured empty group'
)
assert.equal(tasks[0].route, '/fde/ai-runs')

assert.equal(measuredScore(1), 1, 'one point on a 100-point vector scale stays one point')
assert.equal(measuredScore(1, 'ratio'), 100)
assert.equal(taskStatusRows({ aiRun: { failed: null } } as any)[0].available, false)
assert.equal(taskStatusRows({ aiRun: null } as any)[0].available, false)
