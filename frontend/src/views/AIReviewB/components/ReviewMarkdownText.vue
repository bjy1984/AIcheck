<script setup lang="ts">
import { computed } from 'vue'
import type { ReviewBReference } from '@/types/ai-review-b'
import { normalizeMineruMarkdownForDisplay } from '@/utils/mineruMarkdownDisplay'

type InlinePart = {
  type: 'text' | 'strong' | 'code'
  text: string
  reference?: ReviewBReference
}

type MarkdownBlock =
  | { type: 'heading'; level: number; content: InlinePart[] }
  | { type: 'paragraph'; content: InlinePart[] }
  | { type: 'list'; ordered: boolean; items: InlinePart[][] }
  | { type: 'table'; header: InlinePart[][]; rows: InlinePart[][][] }

const props = withDefaults(
  defineProps<{
    content: string
    references?: ReviewBReference[]
  }>(),
  { references: () => [] }
)

const emit = defineEmits<{
  'open-reference': [reference: ReviewBReference]
}>()

const referenceByKey = computed(() => {
  const entries = new Map<string, ReviewBReference>()
  for (const reference of props.references) {
    entries.set(`${reference.kind}:${reference.referenceId}`.toLowerCase(), reference)
    entries.set(reference.referenceId.toLowerCase(), reference)
  }
  return entries
})

const referenceAliases = computed(() => {
  const entries: Array<{ alias: string; normalized: string; reference: ReviewBReference }> = []
  const seen = new Set<string>()
  for (const reference of props.references) {
    const aliases = [reference.referenceId, reference.label, ...(reference.aliases || [])]
    for (const value of aliases) {
      const alias = String(value || '').trim()
      if (alias.length < 4) continue
      const normalized = alias.toLowerCase()
      const key = `${normalized}:${reference.kind}:${reference.referenceId}`
      if (seen.has(key)) continue
      seen.add(key)
      entries.push({ alias, normalized, reference })
    }
  }
  return entries.sort((left, right) => right.alias.length - left.alias.length)
})

const splitReferenceAliases = (part: InlinePart): InlinePart[] => {
  if (part.reference || !part.text) return [part]
  const result: InlinePart[] = []
  const normalizedText = part.text.toLowerCase()
  let cursor = 0
  while (cursor < part.text.length) {
    let next: { index: number; alias: string; reference: ReviewBReference } | undefined
    for (const entry of referenceAliases.value) {
      const index = normalizedText.indexOf(entry.normalized, cursor)
      if (index < 0) continue
      if (
        !next ||
        index < next.index ||
        (index === next.index && entry.alias.length > next.alias.length)
      ) {
        next = { index, alias: entry.alias, reference: entry.reference }
      }
    }
    if (!next) {
      result.push({ ...part, text: part.text.slice(cursor) })
      break
    }
    if (next.index > cursor) result.push({ ...part, text: part.text.slice(cursor, next.index) })
    const matchedText = part.text.slice(next.index, next.index + next.alias.length)
    result.push({
      ...part,
      text:
        next.reference.kind === 'basis' &&
        matchedText.toLowerCase() === next.reference.referenceId.toLowerCase()
          ? next.reference.label
          : matchedText,
      reference: next.reference
    })
    cursor = next.index + next.alias.length
  }
  return result.filter((item) => item.text)
}

const inlineParts = (value: string): InlinePart[] => {
  const parts = value
    .split(/(\[[^\]]+\]\((?:basis|evidence):[^)]+\)|\*\*[^*]+\*\*|`[^`]+`)/g)
    .filter(Boolean)
  const resolved = parts.flatMap<InlinePart>((part) => {
    const citation = part.match(/^\[([^\]]+)\]\((basis|evidence):([^)]+)\)$/)
    if (citation) {
      const reference = referenceByKey.value.get(`${citation[2]}:${citation[3]}`.toLowerCase())
      const citationText =
        reference?.kind === 'basis' &&
        citation[1].toLowerCase() === reference.referenceId.toLowerCase()
          ? reference.label
          : citation[1]
      return [{ type: 'text', text: citationText, reference }]
    }
    if (part.startsWith('**') && part.endsWith('**')) {
      return splitReferenceAliases({ type: 'strong', text: part.slice(2, -2) })
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return splitReferenceAliases({ type: 'code', text: part.slice(1, -1) })
    }
    return splitReferenceAliases({ type: 'text', text: part })
  })
  const basisReferences = Array.from(
    new Map(
      resolved
        .filter((part) => part.reference?.kind === 'basis')
        .map((part) => [part.reference?.referenceId, part.reference as ReviewBReference])
    ).values()
  )
  // 缺失材料尚无文件原文时，将同一条建议中的材料名称定位到它唯一对应的条款原文。
  if (basisReferences.length === 1) {
    return resolved.map((part) =>
      part.type === 'strong' && !part.reference ? { ...part, reference: basisReferences[0] } : part
    )
  }
  return resolved
}

const referenceTitle = (reference: ReviewBReference) =>
  reference.kind === 'basis' ? '查看标准条款原文' : '查看证据文件原文'

const tableCells = (line: string) =>
  line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())

const isTableSeparator = (line: string) => {
  const cells = tableCells(line)
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

const isBlockStart = (lines: string[], index: number) => {
  const line = lines[index] || ''
  if (!line.trim()) return true
  if (/^#{1,6}\s+/.test(line) || /^[-*]\s+/.test(line) || /^\d+\.\s+/.test(line)) return true
  return line.includes('|') && isTableSeparator(lines[index + 1] || '')
}

const blocks = computed<MarkdownBlock[]>(() => {
  const lines = normalizeMineruMarkdownForDisplay(props.content).replace(/\r/g, '').split('\n')
  const result: MarkdownBlock[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      result.push({ type: 'heading', level: heading[1].length, content: inlineParts(heading[2]) })
      index += 1
      continue
    }

    if (line.includes('|') && isTableSeparator(lines[index + 1] || '')) {
      const header = tableCells(line).map(inlineParts)
      const rows: InlinePart[][][] = []
      index += 2
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
        rows.push(tableCells(lines[index]).map(inlineParts))
        index += 1
      }
      result.push({ type: 'table', header, rows })
      continue
    }

    const unordered = line.match(/^[-*]\s+(.+)$/)
    const ordered = line.match(/^\d+\.\s+(.+)$/)
    if (unordered || ordered) {
      const orderedList = Boolean(ordered)
      const items: InlinePart[][] = []
      const pattern = orderedList ? /^\d+\.\s+(.+)$/ : /^[-*]\s+(.+)$/
      while (index < lines.length) {
        const match = lines[index].match(pattern)
        if (!match) break
        items.push(inlineParts(match[1]))
        index += 1
      }
      result.push({ type: 'list', ordered: orderedList, items })
      continue
    }

    const paragraphLines = [line.trim()]
    index += 1
    while (index < lines.length && !isBlockStart(lines, index)) {
      paragraphLines.push(lines[index].trim())
      index += 1
    }
    result.push({ type: 'paragraph', content: inlineParts(paragraphLines.join(' ')) })
  }

  return result
})
</script>

<template>
  <div class="review-markdown">
    <template v-for="(block, blockIndex) in blocks" :key="blockIndex">
      <component
        :is="`h${Math.min(block.level, 4)}`"
        v-if="block.type === 'heading'"
        :class="['markdown-heading', `is-level-${block.level}`]"
      >
        <template v-for="(part, partIndex) in block.content" :key="partIndex">
          <button
            v-if="part.reference"
            type="button"
            :class="['markdown-reference', `is-${part.type}`]"
            :title="referenceTitle(part.reference)"
            :aria-label="`${part.text}，${referenceTitle(part.reference)}`"
            @click="emit('open-reference', part.reference)"
          >
            <strong v-if="part.type === 'strong'">{{ part.text }}</strong>
            <code v-else-if="part.type === 'code'">{{ part.text }}</code>
            <template v-else>{{ part.text }}</template>
          </button>
          <strong v-else-if="part.type === 'strong'">{{ part.text }}</strong>
          <code v-else-if="part.type === 'code'">{{ part.text }}</code>
          <template v-else>{{ part.text }}</template>
        </template>
      </component>

      <p v-else-if="block.type === 'paragraph'">
        <template v-for="(part, partIndex) in block.content" :key="partIndex">
          <button
            v-if="part.reference"
            type="button"
            :class="['markdown-reference', `is-${part.type}`]"
            :title="referenceTitle(part.reference)"
            :aria-label="`${part.text}，${referenceTitle(part.reference)}`"
            @click="emit('open-reference', part.reference)"
          >
            <strong v-if="part.type === 'strong'">{{ part.text }}</strong>
            <code v-else-if="part.type === 'code'">{{ part.text }}</code>
            <template v-else>{{ part.text }}</template>
          </button>
          <strong v-else-if="part.type === 'strong'">{{ part.text }}</strong>
          <code v-else-if="part.type === 'code'">{{ part.text }}</code>
          <template v-else>{{ part.text }}</template>
        </template>
      </p>

      <component :is="block.ordered ? 'ol' : 'ul'" v-else-if="block.type === 'list'">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex">
          <template v-for="(part, partIndex) in item" :key="partIndex">
            <button
              v-if="part.reference"
              type="button"
              :class="['markdown-reference', `is-${part.type}`]"
              :title="referenceTitle(part.reference)"
              :aria-label="`${part.text}，${referenceTitle(part.reference)}`"
              @click="emit('open-reference', part.reference)"
            >
              <strong v-if="part.type === 'strong'">{{ part.text }}</strong>
              <code v-else-if="part.type === 'code'">{{ part.text }}</code>
              <template v-else>{{ part.text }}</template>
            </button>
            <strong v-else-if="part.type === 'strong'">{{ part.text }}</strong>
            <code v-else-if="part.type === 'code'">{{ part.text }}</code>
            <template v-else>{{ part.text }}</template>
          </template>
        </li>
      </component>

      <div v-else-if="block.type === 'table'" class="markdown-table-wrap">
        <table>
          <thead>
            <tr>
              <th v-for="(cell, cellIndex) in block.header" :key="cellIndex">
                <template v-for="(part, partIndex) in cell" :key="partIndex">
                  <button
                    v-if="part.reference"
                    type="button"
                    :class="['markdown-reference', `is-${part.type}`]"
                    :title="referenceTitle(part.reference)"
                    :aria-label="`${part.text}，${referenceTitle(part.reference)}`"
                    @click="emit('open-reference', part.reference)"
                  >
                    <strong v-if="part.type === 'strong'">{{ part.text }}</strong>
                    <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                    <template v-else>{{ part.text }}</template>
                  </button>
                  <strong v-else-if="part.type === 'strong'">{{ part.text }}</strong>
                  <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                  <template v-else>{{ part.text }}</template>
                </template>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
              <td v-for="(cell, cellIndex) in row" :key="cellIndex">
                <template v-for="(part, partIndex) in cell" :key="partIndex">
                  <button
                    v-if="part.reference"
                    type="button"
                    :class="['markdown-reference', `is-${part.type}`]"
                    :title="referenceTitle(part.reference)"
                    :aria-label="`${part.text}，${referenceTitle(part.reference)}`"
                    @click="emit('open-reference', part.reference)"
                  >
                    <strong v-if="part.type === 'strong'">{{ part.text }}</strong>
                    <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                    <template v-else>{{ part.text }}</template>
                  </button>
                  <strong v-else-if="part.type === 'strong'">{{ part.text }}</strong>
                  <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                  <template v-else>{{ part.text }}</template>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.review-markdown {
  font-size: 14px;
  line-height: 1.75;
  color: inherit;
}

.review-markdown p {
  margin: 0 0 10px;
}

.review-markdown p:last-child {
  margin-bottom: 0;
}

.markdown-heading {
  margin: 17px 0 8px;
  color: #182230;
}

.markdown-heading:first-child {
  margin-top: 0;
}

.markdown-heading.is-level-1,
.markdown-heading.is-level-2 {
  font-size: 16px;
}

.markdown-heading.is-level-3,
.markdown-heading.is-level-4,
.markdown-heading.is-level-5,
.markdown-heading.is-level-6 {
  font-size: 14px;
}

.review-markdown ul,
.review-markdown ol {
  padding-left: 22px;
  margin: 4px 0 12px;
}

.review-markdown li {
  padding-left: 2px;
  margin: 3px 0;
}

.review-markdown code {
  padding: 1px 5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.9em;
  background: #f2f4f7;
  border: 1px solid #e4e7ec;
  border-radius: 4px;
}

.markdown-reference {
  display: inline;
  padding: 0;
  margin: 0;
  font: inherit;
  color: #1267d6;
  text-align: inherit;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-bottom: 1px dotted currentcolor;
}

.markdown-reference:hover,
.markdown-reference:focus-visible {
  color: #004db3;
  background: #eef5ff;
  outline: none;
}

.markdown-reference code {
  color: inherit;
}

.markdown-table-wrap {
  margin: 10px 0 14px;
  overflow-x: auto;
  border: 1px solid #e4e7ec;
  border-radius: 8px;
}

.markdown-table-wrap table {
  width: 100%;
  min-width: 460px;
  border-collapse: collapse;
}

.markdown-table-wrap th,
.markdown-table-wrap td {
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.55;
  text-align: left;
  vertical-align: top;
  border-right: 1px solid #eaecf0;
  border-bottom: 1px solid #eaecf0;
}

.markdown-table-wrap th {
  color: #344054;
  background: #f8fafc;
}

.markdown-table-wrap tr:last-child td {
  border-bottom: 0;
}

.markdown-table-wrap th:last-child,
.markdown-table-wrap td:last-child {
  border-right: 0;
}
</style>
