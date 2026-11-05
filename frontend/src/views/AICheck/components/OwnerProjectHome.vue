<script setup lang="ts">
/**
 * 建设方首页（2026-11-04 按手机简化稿重做）：进度、需要关注、最新动态、报告与归档、全部节点。
 * 单栏、没有表格、手机上不横滑；节点细节（资料要求、已挂载资料）点进节点才看。
 * 数字和口径都在 ../ownerHome.ts。
 */
import { computed, ref } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'

import type {
  ArchiveItem,
  MessageItem,
  Project,
  ProjectTreeNode,
  ReportVersion
} from '@/types/aicheck'
import {
  OWNER_BUCKET_LABELS,
  ownerAttentionNodes,
  ownerBucket,
  ownerFeed,
  ownerProgress,
  ownerReportsState,
  ownerStatusCounts,
  type OwnerBucket
} from '../ownerHome'
import AuditStatusTag, { type AuditStatusTone } from './AuditStatusTag.vue'
import FileTypeIcon from './FileTypeIcon.vue'

const props = defineProps<{
  project?: Project
  nodes: ProjectTreeNode[]
  metrics: Array<{ key: string; label: string; value: string | number }>
  reports: ReportVersion[]
  archiveItems: ArchiveItem[]
  messages: MessageItem[]
  reportArchiveLoading: boolean
  reportArchiveLoaded: boolean
  reportArchiveIssue?: string
}>()

const emit = defineEmits<{
  openNode: [node: ProjectTreeNode]
  openMessages: []
  openReport: [reportId: string]
  downloadArchiveItem: [item: ArchiveItem]
  downloadArchivePackage: []
  retryReportArchive: []
}>()

const TONES: Record<OwnerBucket, AuditStatusTone> = {
  passed: 'green',
  reviewing: 'blue',
  correction: 'red',
  pending: 'gray'
}
const STAT_ORDER: OwnerBucket[] = ['passed', 'reviewing', 'correction', 'pending']

const progress = computed(() => ownerProgress(props.metrics))
const counts = computed(() => ownerStatusCounts(props.nodes))
const attention = computed(() => ownerAttentionNodes(props.nodes, props.messages))
const feed = computed(() => ownerFeed(props.messages, props.reports, props.archiveItems))
const reportsState = computed(() =>
  ownerReportsState({
    loading: props.reportArchiveLoading,
    loaded: props.reportArchiveLoaded,
    issue: props.reportArchiveIssue
  })
)

const orgsOpen = ref(false)
const orgLine = computed(() =>
  [
    props.project?.contractorOrgName ? `施工 ${props.project.contractorOrgName}` : '',
    props.project?.inspectionOrgName ? `监检 ${props.project.inspectionOrgName}` : ''
  ]
    .filter(Boolean)
    .join(' · ')
)

const filter = ref<'all' | OwnerBucket>('all')
const FILTERS: Array<'all' | OwnerBucket> = ['all', 'correction', 'reviewing', 'passed']
const filterLabel = (key: 'all' | OwnerBucket) =>
  key === 'all' ? '全部' : OWNER_BUCKET_LABELS[key]
const filterCount = (key: 'all' | OwnerBucket) =>
  key === 'all' ? counts.value.total : counts.value[key]
const filteredNodes = computed(() =>
  filter.value === 'all'
    ? props.nodes
    : props.nodes.filter((node) => ownerBucket(String(node.status || '')) === filter.value)
)
const selectFilter = (key: 'all' | OwnerBucket) => {
  filter.value = key
  showAllNodes.value = false
}
/** 69 个节点一次铺开太长：先列 12 个，要看再展开。 */
const PREVIEW = 12
const showAllNodes = ref(false)
const visibleNodes = computed(() =>
  showAllNodes.value ? filteredNodes.value : filteredNodes.value.slice(0, PREVIEW)
)

/** 点上面的统计数：筛出这一类节点，并滚到节点列表。 */
const jumpToBucket = (bucket: OwnerBucket) => {
  filter.value = bucket === 'pending' ? 'all' : bucket
  showAllNodes.value = false
  document.getElementById('owner-node-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const nodeTone = (node: ProjectTreeNode) => TONES[ownerBucket(String(node.status || ''))]
const archiveTypeLabel = (item: ArchiveItem) =>
  item.type === 'report' ? '报告' : item.type === 'evidence' ? '证据资料' : '资料'
</script>

<template>
  <div class="owner-home">
    <!-- 页头标题对建设方没信息量，去掉了；读屏仍要有一级标题 -->
    <h1 class="owner-sr-only">建设方工作台 · {{ project?.name || '项目概况' }}</h1>
    <section class="owner-card owner-progress" aria-label="项目进度">
      <span class="owner-eyebrow">建设方 · 只读</span>
      <div class="owner-progress-line">
        <strong class="owner-progress-value">{{ progress.label }}</strong>
        <span
          class="owner-progress-bar"
          role="progressbar"
          :aria-valuenow="progress.percent"
          aria-valuemin="0"
          aria-valuemax="100"
        >
          <span :style="{ width: `${progress.percent}%` }"></span>
        </span>
      </div>
      <div class="owner-stats">
        <button
          v-for="bucket in STAT_ORDER"
          :key="bucket"
          type="button"
          class="owner-stat"
          @click="jumpToBucket(bucket)"
        >
          <i :class="`owner-dot is-${TONES[bucket]}`" aria-hidden="true"></i>
          <span>{{ OWNER_BUCKET_LABELS[bucket] }}</span>
          <strong>{{ counts[bucket] }}</strong>
        </button>
      </div>
      <div class="owner-orgs">
        <span>{{ orgLine || '参建单位未登记' }}</span>
        <button
          type="button"
          class="owner-link"
          :aria-expanded="orgsOpen"
          @click="orgsOpen = !orgsOpen"
        >
          参建单位<ElIcon :class="{ 'is-open': orgsOpen }"><ArrowRight /></ElIcon>
        </button>
      </div>
      <dl v-if="orgsOpen" class="owner-org-list">
        <div>
          <dt>建设单位</dt>
          <dd>{{ project?.ownerOrgName || '—' }}</dd>
        </div>
        <div>
          <dt>施工单位</dt>
          <dd>{{ project?.contractorOrgName || '—' }}</dd>
        </div>
        <div>
          <dt>监检机构</dt>
          <dd>{{ project?.inspectionOrgName || '—' }}</dd>
        </div>
      </dl>
    </section>

    <section v-if="attention.length" class="owner-section" aria-label="需要关注">
      <h2>
        需要关注<span class="owner-count">{{ attention.length }}</span>
      </h2>
      <button
        v-for="item in attention"
        :key="item.node.nodeId"
        type="button"
        class="owner-card owner-attention"
        @click="emit('openNode', item.node)"
      >
        <AuditStatusTag tone="red">需补正</AuditStatusTag>
        <span class="owner-row-main">
          <strong>{{ item.node.nodeId }}. {{ item.node.name }}</strong>
          <small>{{ item.reason }}{{ item.at ? ` · ${item.at}` : '' }}</small>
        </span>
        <ElIcon class="owner-chevron"><ArrowRight /></ElIcon>
      </button>
    </section>

    <section class="owner-section" aria-label="最新动态">
      <div class="owner-section-head">
        <h2>最新动态</h2>
        <button type="button" class="owner-link" @click="emit('openMessages')">
          全部<ElIcon><ArrowRight /></ElIcon>
        </button>
      </div>
      <ul v-if="feed.length" class="owner-card owner-feed">
        <li v-for="item in feed" :key="`${item.at}-${item.title}`">
          <i :class="`owner-dot is-${item.tone}`" aria-hidden="true"></i>
          <span>{{ item.title }}</span>
          <small>{{ item.at }}</small>
        </li>
      </ul>
      <p v-else class="owner-card owner-empty">暂时没有新动态。</p>
    </section>

    <section class="owner-section" aria-label="报告与归档">
      <h2>报告与归档</h2>
      <div class="owner-card owner-files">
        <p v-if="reportsState === 'loading'" class="owner-empty">正在加载报告与归档…</p>
        <div v-else-if="reportsState === 'failed'" class="owner-empty is-error">
          <span>报告与归档暂时没加载出来。</span>
          <ElButton size="small" @click="emit('retryReportArchive')">重试</ElButton>
        </div>
        <p v-else-if="reportsState === 'idle'" class="owner-empty">报告与归档待加载。</p>
        <template v-else>
          <!-- 整行就是按钮：手机上按钮最少 44px，行里再套一个框框按钮会很笨重 -->
          <ul v-if="reports.length || archiveItems.length" class="owner-file-list">
            <li v-for="report in reports" :key="report.id">
              <button type="button" class="owner-file-row" @click="emit('openReport', report.id)">
                <FileTypeIcon :file-name="`${report.title}.pdf`" category="报告" />
                <span class="owner-row-main">
                  <strong>{{ report.title }}</strong>
                  <small>报告 · {{ report.status }} · {{ report.versionNo }}</small>
                </span>
                <span class="owner-file-action">查看</span>
              </button>
            </li>
            <li v-for="item in archiveItems" :key="item.id">
              <button
                type="button"
                class="owner-file-row"
                :aria-label="`下载 ${item.name}`"
                @click="emit('downloadArchiveItem', item)"
              >
                <FileTypeIcon :file-name="item.name" />
                <span class="owner-row-main">
                  <strong>{{ item.name }}</strong>
                  <small
                    >{{ archiveTypeLabel(item)
                    }}{{ item.nodeId ? ` · 节点 ${item.nodeId}` : '' }}</small
                  >
                </span>
                <span class="owner-file-action">下载</span>
              </button>
            </li>
          </ul>
          <p v-else class="owner-empty"
            >还没有报告和归档资料：节点通过审查、报告签发后会出现在这里。</p
          >
          <button
            v-if="archiveItems.length"
            type="button"
            class="owner-package"
            @click="emit('downloadArchivePackage')"
          >
            下载完整归档包
          </button>
        </template>
      </div>
    </section>

    <section id="owner-node-list" class="owner-section" aria-label="全部节点">
      <h2>全部节点</h2>
      <div class="owner-card">
        <div class="owner-filter" role="tablist" aria-label="按状态筛选节点">
          <button
            v-for="key in FILTERS"
            :key="key"
            type="button"
            role="tab"
            :aria-selected="filter === key"
            :class="['owner-filter-item', { 'is-active': filter === key }]"
            @click="selectFilter(key)"
          >
            {{ filterLabel(key) }} {{ filterCount(key) }}
          </button>
        </div>
        <ul v-if="visibleNodes.length" class="owner-node-list">
          <li v-for="node in visibleNodes" :key="node.nodeId">
            <button type="button" class="owner-node-row" @click="emit('openNode', node)">
              <span class="owner-node-name">{{ node.nodeId }}. {{ node.name }}</span>
              <AuditStatusTag :tone="nodeTone(node)">{{ node.status }}</AuditStatusTag>
              <ElIcon class="owner-chevron"><ArrowRight /></ElIcon>
            </button>
          </li>
        </ul>
        <p v-else class="owner-empty">没有这类节点。</p>
        <button
          v-if="!showAllNodes && filteredNodes.length > visibleNodes.length"
          type="button"
          class="owner-more"
          @click="showAllNodes = true"
        >
          展开全部 {{ filteredNodes.length }} 个节点
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.owner-home {
  display: grid;
  max-width: 860px;
  margin: 0 auto;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
}

.owner-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.owner-card {
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 12px;
}

.owner-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
}

.owner-section h2,
.owner-section-head h2 {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 0;
  font-size: 17px;
  line-height: 24px;
  color: #172033;
}

.owner-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.owner-count {
  display: inline-grid;
  height: 20px;
  min-width: 20px;
  padding: 0 6px;
  font-size: 12px;
  color: #fff;
  background: #d64545;
  border-radius: 999px;
  place-items: center;
}

.owner-link {
  display: inline-flex;
  min-height: 32px;
  padding: 0;
  font: inherit;
  font-size: 14px;
  color: var(--el-color-primary, #2f6bff);
  white-space: nowrap;
  cursor: pointer;
  background: none;
  border: 0;
  flex: 0 0 auto;
  gap: 2px;
  align-items: center;
}

.owner-link .el-icon {
  transition: transform 0.18s ease;
}

.owner-link .el-icon.is-open {
  transform: rotate(90deg);
}

/* 进度卡 */
.owner-eyebrow {
  font-size: 13px;
  color: #667085;
}

.owner-progress-line {
  display: flex;
  gap: 14px;
  align-items: center;
  margin: 6px 0 12px;
}

.owner-progress-value {
  font-size: 30px;
  line-height: 36px;
  color: #172033;
  font-variant-numeric: tabular-nums;
}

.owner-progress-bar {
  position: relative;
  height: 8px;
  overflow: hidden;
  background: #edf1f6;
  border-radius: 999px;
  flex: 1 1 auto;
}

.owner-progress-bar > span {
  position: absolute;
  inset: 0 auto 0 0;
  background: #1f9d55;
  border-radius: 999px;
}

.owner-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.owner-stat {
  display: grid;
  min-height: 56px;
  padding: 8px 10px;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: #f6f8fb;
  border: 0;
  border-radius: 10px;
  grid-template-columns: auto minmax(0, 1fr);
  column-gap: 6px;
  align-items: center;
}

.owner-stat span {
  overflow: hidden;
  font-size: 13px;
  color: #475467;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.owner-stat strong {
  grid-column: 2;
  font-size: 18px;
  color: #172033;
  font-variant-numeric: tabular-nums;
}

.owner-stat:hover,
.owner-stat:focus-visible {
  background: #eef4ff;
  outline: 0;
}

.owner-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  background: #8a94a6;
  border-radius: 50%;
}

.owner-dot.is-green {
  background: #1f9d55;
}

.owner-dot.is-blue {
  background: #2f6bff;
}

.owner-dot.is-red {
  background: #d64545;
}

.owner-orgs {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding-top: 10px;
  margin-top: 12px;
  font-size: 13px;
  color: #667085;
  border-top: 1px solid #eef1f6;
}

.owner-orgs > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.owner-org-list {
  display: grid;
  margin: 8px 0 0;
  gap: 6px;
}

.owner-org-list > div {
  display: flex;
  gap: 12px;
  font-size: 13px;
}

.owner-org-list dt {
  flex: 0 0 64px;
  color: #667085;
}

.owner-org-list dd {
  margin: 0;
  color: #172033;
}

/* 需要关注：细边框＋浅状态底色 */
.owner-attention {
  display: flex;
  gap: 12px;
  align-items: center;
  width: 100%;
  min-height: 64px;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: #fff7f6;
  border-color: #f0c8c3;
}

.owner-row-main {
  display: grid;
  min-width: 0;
  flex: 1 1 auto;
  gap: 2px;
}

.owner-row-main strong {
  overflow: hidden;
  font-size: 14px;
  font-weight: 500;
  line-height: 20px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.owner-row-main small {
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.owner-chevron {
  flex: 0 0 auto;
  color: #98a2b3;
}

/* 最新动态。下面几个列表的列宽都要能缩：auto 列会被不换行的长节点名、长文件名撑出右边界 */
.owner-feed {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  padding-top: 4px;
  padding-bottom: 4px;
  margin: 0;
  list-style: none;
}

.owner-feed li {
  display: flex;
  gap: 10px;
  align-items: center;
  min-height: 44px;
  font-size: 14px;
  color: #27364b;
}

.owner-feed li + li {
  border-top: 1px solid #eef1f6;
}

.owner-feed li > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1 1 auto;
}

.owner-feed small {
  flex: 0 0 auto;
  font-size: 12px;
  color: #98a2b3;
  font-variant-numeric: tabular-nums;
}

.owner-empty {
  margin: 0;
  font-size: 13px;
  line-height: 20px;
  color: #667085;
}

.owner-empty.is-error {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  color: #b42318;
}

/* 报告与归档 */
.owner-files {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
}

.owner-file-list {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  padding: 0;
  margin: 0;
  list-style: none;
}

.owner-file-row {
  display: flex;
  gap: 12px;
  align-items: center;
  width: 100%;
  min-height: 56px;
  padding: 0;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: none;
  border: 0;
}

.owner-file-row:hover .owner-row-main strong {
  color: var(--el-color-primary, #2f6bff);
}

.owner-file-action {
  flex: 0 0 auto;
  padding: 4px 12px;
  font-size: 13px;
  font-weight: 500;
  color: var(--el-color-primary, #2f6bff);
  background: #eef4ff;
  border-radius: 999px;
}

.owner-file-list li + li {
  border-top: 1px solid #eef1f6;
}

.owner-package {
  width: 100%;
  min-height: 44px;
  font: inherit;
  font-size: 14px;
  font-weight: 500;
  color: var(--el-color-primary, #2f6bff);
  cursor: pointer;
  background: #eef4ff;
  border: 0;
  border-radius: 10px;
}

.owner-package:hover {
  background: #e3ecff;
}

/* 全部节点 */
.owner-filter {
  display: grid;
  margin-bottom: 6px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.owner-filter-item {
  min-height: 36px;
  padding: 0 4px;
  overflow: hidden;
  font: inherit;
  font-size: 13px;
  color: #475467;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  background: #f6f8fb;
  border: 0;
  border-radius: 8px;
}

.owner-filter-item.is-active {
  font-weight: 600;
  color: #fff;
  background: var(--el-color-primary, #2f6bff);
}

.owner-node-list {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  padding: 0;
  margin: 0;
  list-style: none;
}

.owner-node-list li + li {
  border-top: 1px solid #eef1f6;
}

.owner-node-row {
  display: flex;
  gap: 10px;
  align-items: center;
  width: 100%;
  min-height: 48px;
  padding: 0;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: none;
  border: 0;
}

.owner-node-name {
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1 1 auto;
}

.owner-node-row:hover .owner-node-name {
  color: var(--el-color-primary, #2f6bff);
}

.owner-more {
  width: 100%;
  min-height: 40px;
  margin-top: 6px;
  font: inherit;
  font-size: 13px;
  color: var(--el-color-primary, #2f6bff);
  cursor: pointer;
  background: none;
  border: 0;
  border-top: 1px solid #eef1f6;
}
</style>
