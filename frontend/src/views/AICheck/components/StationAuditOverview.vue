<script setup lang="ts">
/**
 * 监检项目总览：按工位分组看节点通过与否（2026-11-03 用户确认的效果图第三版）。
 *
 * 左边固定 A～I 工位，每个带一条小进度条和计数，有未通过的加红点；右边是选中工位的节点，
 * 按「未通过 → 待补资料 → 需人工确认 → 通过 → 未开始审核」分组，每行一句原因、一个动作、
 * 点整行在原地展开详情（结论分布、不过的检查项、缺的资料、流程各步），不跳页；只有动作按钮和
 * 「进入节点」才跳。顶部一行细条给全项目合计。数的是节点，不是审计项（标题写明）。
 */
import { computed, ref, watch } from 'vue'
import { ElButton, ElEmpty, ElIcon, ElSkeleton, ElTag } from 'element-plus'
import { ArrowRight, Check, Close, MoreFilled, WarningFilled } from '@element-plus/icons-vue'
import type {
  InspectionAuditOverviewNode,
  InspectionNodeConclusionGroup,
  InspectionStation,
  ProjectTreeNode
} from '@/types/aicheck'
import {
  STATION_GROUP_ACTIONS,
  STATION_GROUP_LABELS,
  STATION_GROUP_ORDER,
  buildStationOverview,
  conclusionReason,
  conclusionSourceTag,
  nodeDetail
} from './stationOverview'

const props = defineProps<{
  items: InspectionAuditOverviewNode[]
  stations?: InspectionStation[]
  loading?: boolean
  auditItemTotal?: number
}>()
const emit = defineEmits<{
  open: [node: ProjectTreeNode, group: InspectionNodeConclusionGroup]
}>()

const overview = computed(() => buildStationOverview(props.items, props.stations || []))
const selectedStationId = ref('')
watch(
  () => overview.value.stations,
  (stations) => {
    if (stations.some((station) => station.stationId === selectedStationId.value)) return
    // 默认选第一个有未通过的工位，没有就选第一个有待处理的，再没有就第一个
    const pick =
      stations.find((station) => station.counts.failed) ||
      stations.find((station) => station.counts.needs_materials || station.counts.needs_human) ||
      stations[0]
    selectedStationId.value = pick?.stationId || ''
  },
  { immediate: true }
)
const selectedStation = computed(() =>
  overview.value.stations.find((station) => station.stationId === selectedStationId.value)
)
const nodeTotal = computed(() => props.items.length)
const summaryChips = computed(() =>
  STATION_GROUP_ORDER.map((group) => ({
    group,
    label: STATION_GROUP_LABELS[group],
    value: overview.value.totals[group]
  }))
)
const groupsOf = (station: NonNullable<typeof selectedStation.value>) =>
  STATION_GROUP_ORDER.map((group) => ({
    group,
    label: STATION_GROUP_LABELS[group],
    nodes: station.nodes.filter((node) => node.group === group)
  })).filter((section) => section.nodes.length)
const stationLine = (counts: Record<InspectionNodeConclusionGroup, number>) =>
  [
    counts.passed && `通过 ${counts.passed}`,
    counts.failed && `未通过 ${counts.failed}`,
    counts.needs_materials + counts.needs_human &&
      `待处理 ${counts.needs_materials + counts.needs_human}`,
    counts.not_started && `未审 ${counts.not_started}`
  ]
    .filter(Boolean)
    .join(' · ')
const width = (value: number, total: number) => (total ? `${(value / total) * 100}%` : '0')
// 展开是本地状态：切工位不收起，回来还是原样
const expanded = ref(new Set<number>())
const toggle = (nodeId: number) => {
  const next = new Set(expanded.value)
  if (next.has(nodeId)) next.delete(nodeId)
  else next.add(nodeId)
  expanded.value = next
}
</script>

<template>
  <section class="station-overview" aria-label="按工位查看审计结果">
    <ElSkeleton v-if="loading && !items.length" :rows="6" animated />
    <ElEmpty v-else-if="!items.length" description="这个项目还没有节点" :image-size="72" />
    <template v-else>
      <div class="station-summary" aria-label="全项目合计">
        <p class="station-summary-unit">
          按节点统计（共 {{ nodeTotal }} 个节点<template v-if="auditItemTotal">
            / {{ auditItemTotal }} 个审计项</template
          >）
        </p>
        <ul class="station-summary-chips">
          <li v-for="chip in summaryChips" :key="chip.group" :class="`is-${chip.group}`">
            <span class="dot" aria-hidden="true"></span>
            {{ chip.label }} <strong>{{ chip.value }}</strong>
            <small v-if="chip.group === 'passed' && overview.confirmedPassed"
              >（已确认 {{ overview.confirmedPassed }}）</small
            >
          </li>
        </ul>
        <div class="station-bar" aria-hidden="true">
          <span
            v-for="chip in summaryChips"
            :key="chip.group"
            :class="`is-${chip.group}`"
            :style="{ width: width(chip.value, nodeTotal) }"
          ></span>
        </div>
      </div>

      <div class="station-body">
        <nav class="station-list" aria-label="工位">
          <h3>工位</h3>
          <button
            v-for="station in overview.stations"
            :key="station.stationId"
            type="button"
            :class="['station-item', { 'is-selected': station.stationId === selectedStationId }]"
            :aria-pressed="station.stationId === selectedStationId"
            @click="selectedStationId = station.stationId"
          >
            <span class="station-item-name">
              <span v-if="station.counts.failed" class="failure-dot" aria-label="有未通过"></span>
              {{ station.stationId }} {{ station.stationName }}
            </span>
            <span class="station-bar station-bar--mini" aria-hidden="true">
              <span
                v-for="group in STATION_GROUP_ORDER"
                :key="group"
                :class="`is-${group}`"
                :style="{ width: width(station.counts[group], station.nodes.length) }"
              ></span>
            </span>
            <small>{{ stationLine(station.counts) }}</small>
          </button>
        </nav>

        <div v-if="selectedStation" class="station-detail">
          <h3>
            {{ selectedStation.stationId }} {{ selectedStation.stationName }}
            <small>· {{ selectedStation.nodes.length }} 个节点</small>
          </h3>
          <section
            v-for="section in groupsOf(selectedStation)"
            :key="section.group"
            :class="['station-group', `is-${section.group}`]"
          >
            <h4>{{ section.label }}（{{ section.nodes.length }}）</h4>
            <div
              v-for="row in section.nodes"
              :key="row.node.nodeId"
              :class="['station-node-card', { 'is-expanded': expanded.has(row.node.nodeId) }]"
            >
              <div
                class="station-node"
                role="button"
                tabindex="0"
                :aria-expanded="expanded.has(row.node.nodeId)"
                @click="toggle(row.node.nodeId)"
                @keydown.enter.prevent="toggle(row.node.nodeId)"
              >
                <span class="station-node-id">{{ row.node.nodeId }}</span>
                <span class="station-node-main">
                  <span class="station-node-name">{{ row.node.name }}</span>
                  <small v-if="conclusionReason(row)" class="station-node-reason">{{
                    conclusionReason(row)
                  }}</small>
                </span>
                <ElTag
                  v-if="conclusionSourceTag(row)"
                  size="small"
                  effect="plain"
                  :type="conclusionSourceTag(row)!.tone"
                  >{{ conclusionSourceTag(row)!.text }}</ElTag
                >
                <ElButton
                  v-if="STATION_GROUP_ACTIONS[row.group]"
                  size="small"
                  type="primary"
                  plain
                  @click.stop="emit('open', row.node, row.group)"
                  >{{ STATION_GROUP_ACTIONS[row.group] }}</ElButton
                >
                <ElIcon class="station-node-chevron" aria-hidden="true"><ArrowRight /></ElIcon>
              </div>
              <div v-if="expanded.has(row.node.nodeId)" class="station-node-detail">
                <template
                  v-for="detail in [nodeDetail(row)]"
                  :key="`${row.node.nodeId}-${detail.process.length}`"
                >
                  <dl>
                    <div v-if="detail.atomicSummary">
                      <dt>审计项结论</dt>
                      <dd>{{ detail.atomicSummary }}</dd>
                    </div>
                    <div v-if="detail.humanOpinion">
                      <dt>监检意见</dt>
                      <dd>{{ detail.humanOpinion }}</dd>
                    </div>
                    <div v-if="detail.failedChecks.length">
                      <dt>未满足</dt>
                      <dd>
                        <ul>
                          <li v-for="check in detail.failedChecks" :key="check">{{ check }}</li>
                        </ul>
                      </dd>
                    </div>
                    <div v-else-if="detail.reasonText">
                      <dt>原因</dt>
                      <dd>{{ detail.reasonText }}</dd>
                    </div>
                    <div v-if="detail.materials">
                      <dt>必传资料</dt>
                      <dd class="station-materials">
                        <span class="station-materials-count">
                          <strong>{{ detail.materials.done }}</strong> /
                          {{ detail.materials.total }} 已齐
                        </span>
                        <span
                          class="station-materials-meter"
                          role="presentation"
                          :style="{
                            '--done': `${detail.materials.total ? (detail.materials.done / detail.materials.total) * 100 : 0}%`
                          }"
                        ></span>
                        <template v-if="detail.materials.missing.length">
                          <span class="station-materials-missing-title"
                            >还缺 {{ detail.materials.missing.length }} 项</span
                          >
                          <ul class="station-materials-missing">
                            <li v-for="item in detail.materials.missing" :key="item">{{ item }}</li>
                          </ul>
                        </template>
                      </dd>
                    </div>
                    <div v-if="detail.process.length">
                      <dt>流程</dt>
                      <dd>
                        <ol class="station-flow" aria-label="节点流程">
                          <li
                            v-for="step in detail.process"
                            :key="step.key"
                            :class="`is-${step.status}`"
                            :title="step.summary"
                          >
                            <span class="station-flow-node" aria-hidden="true">
                              <ElIcon v-if="step.status === 'completed'"><Check /></ElIcon>
                              <ElIcon v-else-if="step.status === 'failed'"><Close /></ElIcon>
                              <ElIcon v-else-if="step.status === 'needs_attention'"
                                ><WarningFilled
                              /></ElIcon>
                              <ElIcon v-else-if="step.status === 'in_progress'"
                                ><MoreFilled
                              /></ElIcon>
                            </span>
                            <span class="station-flow-label">{{ step.label }}</span>
                            <small class="station-flow-status">{{ step.statusLabel }}</small>
                          </li>
                        </ol>
                        <ul
                          v-if="detail.process.some((step) => step.needsAction)"
                          class="station-flow-notes"
                        >
                          <li
                            v-for="step in detail.process.filter((item) => item.needsAction)"
                            :key="step.key"
                          >
                            <strong>{{ step.label }}</strong
                            >{{ step.summary }}
                          </li>
                        </ul>
                      </dd>
                    </div>
                  </dl>
                  <ElButton
                    class="station-node-enter"
                    link
                    type="primary"
                    @click="emit('open', row.node, row.group)"
                    >进入节点<ElIcon class="el-icon--right"><ArrowRight /></ElIcon
                  ></ElButton>
                </template>
              </div>
            </div>
          </section>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.station-overview {
  --st-failed: #dc2626;
  --st-needs_materials: #d97706;
  --st-needs_human: #7c3aed;
  --st-passed: #16a34a;
  --st-not_started: #9ca3af;
  display: grid;
  gap: 16px;
}
.station-summary {
  padding: 14px 16px;
  background: var(--aicheck-surface, #fff);
  border: 1px solid var(--aicheck-border, #e5e7eb);
  border-radius: 8px;
}
.station-summary-unit {
  margin: 0 0 8px;
  color: var(--aicheck-text-subtle, #667085);
  font-size: 12px;
}
.station-summary-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  margin: 0 0 10px;
  padding: 0;
  list-style: none;
}
.station-summary-chips li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}
.station-summary-chips strong {
  font-size: 18px;
}
.station-summary-chips small {
  color: var(--aicheck-text-subtle, #667085);
}
.dot,
.failure-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.failure-dot {
  background: var(--st-failed);
}
.station-bar {
  display: flex;
  height: 8px;
  overflow: hidden;
  background: #f3f4f6;
  border-radius: 4px;
}
.station-bar--mini {
  height: 5px;
}
.is-failed .dot,
.station-bar .is-failed {
  background: var(--st-failed);
}
.is-needs_materials .dot,
.station-bar .is-needs_materials {
  background: var(--st-needs_materials);
}
.is-needs_human .dot,
.station-bar .is-needs_human {
  background: var(--st-needs_human);
}
.is-passed .dot,
.station-bar .is-passed {
  background: var(--st-passed);
}
.is-not_started .dot,
.station-bar .is-not_started {
  background: var(--st-not_started);
}
.station-body {
  display: grid;
  grid-template-columns: minmax(220px, 30%) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.station-list,
.station-detail {
  min-width: 0;
  padding: 12px;
  background: var(--aicheck-surface, #fff);
  border: 1px solid var(--aicheck-border, #e5e7eb);
  border-radius: 8px;
}
.station-list h3,
.station-detail h3 {
  margin: 4px 4px 10px;
  font-size: 15px;
}
.station-detail h3 small {
  color: var(--aicheck-text-subtle, #667085);
  font-weight: 400;
}
.station-item {
  display: grid;
  gap: 6px;
  width: 100%;
  padding: 10px 8px;
  text-align: left;
  background: none;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}
.station-item + .station-item {
  border-top: 1px solid #f1f2f4;
}
.station-item.is-selected {
  background: #eef4ff;
}
.station-item-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 500;
}
.station-item small {
  color: var(--aicheck-text-subtle, #667085);
}
.station-group + .station-group {
  margin-top: 14px;
}
.station-group h4 {
  margin: 0 4px 8px;
  font-size: 14px;
}
.station-group.is-failed h4 {
  color: var(--st-failed);
}
.station-group.is-needs_materials h4 {
  color: var(--st-needs_materials);
}
.station-group.is-needs_human h4 {
  color: var(--st-needs_human);
}
.station-group.is-passed h4 {
  color: var(--st-passed);
}
.station-group.is-not_started h4 {
  color: var(--st-not_started);
}
.station-node-card {
  border: 1px solid var(--aicheck-border, #e5e7eb);
  border-radius: 6px;
}
.station-node-card + .station-node-card {
  margin-top: 6px;
}
.station-node-card.is-expanded .station-node-chevron {
  transform: rotate(90deg);
}
.station-node-detail {
  padding: 4px 16px 12px 48px;
  border-top: 1px dashed var(--aicheck-border, #e5e7eb);
}
.station-node-detail dl {
  display: grid;
  gap: 6px;
  margin: 8px 0;
}
.station-node-detail dl > div {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr);
  gap: 8px;
}
.station-node-detail dt {
  color: var(--aicheck-text-subtle, #667085);
}
.station-node-detail dd {
  min-width: 0;
  margin: 0;
}
.station-node-detail ul {
  margin: 0;
  padding-left: 18px;
}
.station-materials {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 12px;
  align-items: center;
}
.station-materials-count {
  font-variant-numeric: tabular-nums;
}
.station-materials-count strong {
  font-size: 15px;
}
.station-materials-meter {
  display: block;
  width: 100%;
  max-width: 160px;
  height: 4px;
  background:
    linear-gradient(var(--st-passed), var(--st-passed)) 0 0 / var(--done) 100% no-repeat,
    #eceff3;
  border-radius: 2px;
}
.station-materials-missing-title {
  grid-column: 1 / -1;
  color: var(--st-needs_materials);
  font-size: 12px;
}
.station-materials-missing {
  display: flex;
  flex-wrap: wrap;
  grid-column: 1 / -1;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.station-materials-missing li {
  padding: 2px 8px;
  color: #92400e;
  font-size: 12px;
  line-height: 18px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 4px;
}
.station-flow {
  --flow-node: 20px;
  display: flex;
  margin: 2px 0 0;
  padding: 0;
  padding-bottom: 4px;
  overflow-x: auto;
  list-style: none;
  scrollbar-color: #d0d5dd transparent;
  scrollbar-width: thin;
}
.station-flow li {
  position: relative;
  display: grid;
  flex: 1 0 64px;
  justify-items: center;
  gap: 2px;
  text-align: center;
}
/* 连接线：从上一个节点画到这一个；前一步做完了就是实线绿 */
.station-flow li + li::before {
  position: absolute;
  top: calc(var(--flow-node) / 2 - 1px);
  right: calc(50% + var(--flow-node) / 2 + 4px);
  left: calc(-50% + var(--flow-node) / 2 + 4px);
  height: 2px;
  background: #e5e7eb;
  border-radius: 1px;
  content: '';
}
.station-flow li.is-completed + li::before {
  background: var(--st-passed);
}
.station-flow-node {
  display: grid;
  width: var(--flow-node);
  height: var(--flow-node);
  place-items: center;
  color: #fff;
  font-size: 12px;
  background: #fff;
  border: 2px solid #d0d5dd;
  border-radius: 50%;
}
.station-flow .is-completed .station-flow-node {
  background: var(--st-passed);
  border-color: var(--st-passed);
}
.station-flow .is-in_progress .station-flow-node {
  color: #2f6bff;
  border-color: #2f6bff;
}
.station-flow .is-needs_attention .station-flow-node {
  color: var(--st-needs_materials);
  border-color: var(--st-needs_materials);
}
.station-flow .is-failed .station-flow-node {
  background: var(--st-failed);
  border-color: var(--st-failed);
}
.station-flow-label {
  margin-top: 4px;
  color: #344054;
  font-size: 12px;
  white-space: nowrap;
}
.station-flow-status {
  color: var(--aicheck-text-subtle, #667085);
  font-size: 11px;
}
.station-flow .is-completed .station-flow-status {
  color: var(--st-passed);
}
.station-flow .is-in_progress .station-flow-status {
  color: #2f6bff;
}
.station-flow .is-needs_attention .station-flow-status {
  color: var(--st-needs_materials);
}
.station-flow .is-failed .station-flow-status {
  color: var(--st-failed);
}
.station-flow-notes {
  display: grid;
  gap: 4px;
  margin: 10px 0 0;
  padding: 0;
  font-size: 12px;
  list-style: none;
}
.station-flow-notes strong {
  margin-right: 8px;
  font-weight: 500;
}
.station-node-enter {
  margin-top: 2px;
}
.station-node {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
}
.station-node-card:hover,
.station-node-card:focus-within {
  border-color: var(--el-color-primary, #2f6bff);
}
.station-node:focus-visible {
  outline: none;
}
.station-node-id {
  min-width: 24px;
  color: var(--aicheck-text-subtle, #667085);
  font-variant-numeric: tabular-nums;
}
.station-node-main {
  display: grid;
  flex: 1;
  gap: 2px;
  min-width: 0;
}
.station-node-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.station-node-reason {
  overflow: hidden;
  color: var(--aicheck-text-subtle, #667085);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.station-node-chevron {
  flex: none;
  color: #98a2b3;
  font-size: 14px;
  transition: transform 0.2s cubic-bezier(0.22, 1, 0.36, 1);
}
@media (max-width: 900px) {
  .station-body {
    grid-template-columns: minmax(0, 1fr);
  }
}
/* 窄屏：标签放到内容上方、去掉缩进，流程图留给横向滚动 */
@media (max-width: 640px) {
  .station-node-detail {
    padding: 4px 12px 12px;
  }
  .station-node-detail dl > div {
    grid-template-columns: minmax(0, 1fr);
    gap: 4px;
  }
  .station-flow li {
    flex-basis: 56px;
  }
}
</style>
