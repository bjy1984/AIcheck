import assert from 'node:assert/strict'
import {
  graphLabelLevel,
  graphSearchContext,
  showGraphNodeLabel,
  visibleGraphSelection
} from './knowledgeGraphLabels'

// A 259-node overview keeps its structural names; zoom reveals detail without dropping data.
assert.equal(showGraphNodeLabel('business_pack', graphLabelLevel(1), 259), true)
assert.equal(showGraphNodeLabel('domain_module', graphLabelLevel(1), 259), true)
assert.equal(showGraphNodeLabel('standard', graphLabelLevel(1), 259), false)
assert.equal(showGraphNodeLabel('inspection_node', graphLabelLevel(2.5), 259), true)
assert.equal(showGraphNodeLabel('standard', graphLabelLevel(2.5), 259), false)
assert.equal(showGraphNodeLabel('standard', graphLabelLevel(5), 259), true)
assert.equal(showGraphNodeLabel('standard', graphLabelLevel(1), 259, true), true)
assert.equal(showGraphNodeLabel('standard', graphLabelLevel(1), 12), true)

// Search must not cascade through edges depending on server order.
const edges = [
  { source: 'match', target: 'neighbor' },
  { source: 'neighbor', target: 'unrelated' },
  { source: 'excluded', target: 'match' }
]
const matches = new Set(['match'])
const allowed = new Set(['match', 'neighbor', 'unrelated'])
assert.deepEqual([...graphSearchContext(matches, allowed, edges)], ['match', 'neighbor'])
assert.deepEqual(
  [...graphSearchContext(matches, allowed, [...edges].reverse())],
  ['match', 'neighbor']
)
assert.deepEqual([...matches], ['match'])

console.log('Knowledge graph progressive labels and one-hop search passed')

const fullGraph = new Set(['industrial', 'welder', 'welding'])
const searchResults = new Set(['welder', 'welding'])
assert.equal(visibleGraphSelection('industrial', searchResults), '')
assert.equal(visibleGraphSelection('welder', searchResults), 'welder')
assert.equal(
  visibleGraphSelection('', searchResults),
  '',
  'filtering does not select the first match'
)
assert.equal(visibleGraphSelection('welder', new Set()), '')
const clearedSelection = visibleGraphSelection('industrial', searchResults)
assert.equal(
  visibleGraphSelection(clearedSelection, fullGraph),
  '',
  'clearing a filter does not silently restore an old detail'
)
