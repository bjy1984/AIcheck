<script setup lang="ts">
/* 平台规则送达既有项目（2026-11-04，意见反馈审批方案第三阶段）。
 * 项目建立时冻结了当时的业务规则；平台修好的规则，旧项目要升级后才按新规则判。
 * 先看差在哪、影响哪些节点、那些节点上有几条已有结论，再选项目升级。历史结论不变。 */
import { computed, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElEmpty,
  ElMessage,
  ElMessageBox,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import StaticPageShell from './components/StaticPageShell.vue'
import { applyBusinessPackUpdatesApi, getBusinessPackUpdatesApi } from '@/api/aicheck'
import type { BusinessPackUpdate } from '@/api/aicheck/reviewPolicies'
import { useUserStoreWithOut } from '@/store/modules/user'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import {
  ADMIN_BOUNDARY_BADGE,
  ADMIN_BOUNDARY_TITLE,
  ADMIN_MENU_ROOT,
  ADMIN_MENU_TITLE,
  buildAdminMenuSections
} from './adminMenuTree'

const userStore = useUserStoreWithOut()
const userLabel = computed(
  () => userStore.getUserInfo?.displayName || userStore.getUserInfo?.username || '系统管理员'
)
const menuSections = computed(() =>
  buildAdminMenuSections('/admin/rule-updates', {
    platformAdmin: Boolean(userStore.getUserInfo?.platformAdmin)
  })
)

const items = ref<BusinessPackUpdate[]>([])
const outdatedCount = ref(0)
const loading = ref(false)
const loadError = ref('')
const applying = ref(false)
const selected = ref<BusinessPackUpdate[]>([])

const load = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const res = await getBusinessPackUpdatesApi()
    items.value = res.data?.items || []
    outdatedCount.value = res.data?.outdatedCount || 0
  } catch (error) {
    loadError.value = getAicheckErrorMessage(error, '规则升级信息加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

const changeSummary = (row: BusinessPackUpdate) =>
  [
    ...row.diff.sections.map((section) => {
      const parts = [
        section.changed ? `改 ${section.changed}` : '',
        section.added ? `增 ${section.added}` : '',
        section.removed ? `删 ${section.removed}` : ''
      ].filter(Boolean)
      return `${section.label} ${parts.join('、')}`
    }),
    ...(row.diff.otherChangeLabels || []).map((label) => `${label}有变化`)
  ].join('；')

const nodeSummary = (row: BusinessPackUpdate) => {
  const nodes = row.diff.affectedNodeIds
  if (!nodes.length) return '—'
  return nodes.length > 12
    ? `${nodes.slice(0, 12).join('、')} 等 ${nodes.length} 个`
    : nodes.join('、')
}

const apply = async () => {
  const targets = selected.value.filter((row) => row.upgradable)
  if (!targets.length) return
  const conclusions = targets.reduce((sum, row) => sum + row.affectedConclusionCount, 0)
  try {
    await ElMessageBox.confirm(
      `升级 ${targets.length} 个项目到现行规则。已有结论不会自动改；受影响节点上有 ${conclusions} 条已有结论，要按新规则判需重新发起复核。`,
      '升级项目规则',
      { confirmButtonText: '升级', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  applying.value = true
  try {
    const res = await applyBusinessPackUpdatesApi(
      targets.map((row) => row.projectId),
      { idempotencyKey: `rule-updates-${Date.now()}` }
    )
    const results = res.data?.results || []
    const failed = results.filter((row) => !row.applied)
    /* 挂了资料的清单行不自动改名（会断开挂载），要人工看 */
    const boundKept = results.reduce(
      (sum, row) => sum + (row.boundRequirementIdsNotUpdated?.length || 0),
      0
    )
    const notes = [
      failed.length
        ? `${failed.length} 个没升级：${failed.map((row) => row.reason).join('、')}`
        : '受影响节点建议重新复核',
      boundKept ? `${boundKept} 条已挂资料的清单项没自动改，请人工核对` : ''
    ].filter(Boolean)
    ElMessage({
      type: failed.length || boundKept ? 'warning' : 'success',
      message: `已升级 ${res.data?.appliedCount || 0} 个项目；${notes.join('；')}。`,
      duration: failed.length || boundKept ? 8000 : 3000
    })
    selected.value = []
    await load()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '升级失败，请稍后重试。'))
  } finally {
    applying.value = false
  }
}

const rightCards = computed(() => [
  {
    title: '升级说明',
    rows: [
      { label: '为什么要升级', value: '项目建立时冻结了当时的规则' },
      { label: '升级后', value: '之后的审查按现行规则判' },
      { label: '已有结论', value: '不自动改，要重新复核' }
    ],
    note: '先看「改了什么」和「受影响节点」，确认后再升级。'
  }
])

onMounted(load)
</script>

<template>
  <StaticPageShell
    brand-mark="RU"
    title="规则升级"
    :status="loadError ? '加载异常' : `${outdatedCount} 个项目可升级`"
    :status-tone="loadError ? 'red' : outdatedCount ? 'orange' : 'green'"
    search-placeholder="搜索后台功能"
    :user-label="userLabel"
    :top-stats="[]"
    :menu-title="ADMIN_MENU_TITLE"
    :menu-root="ADMIN_MENU_ROOT"
    :menu-sections="menuSections"
    :boundary-title="ADMIN_BOUNDARY_TITLE"
    :boundary-badge="ADMIN_BOUNDARY_BADGE"
    boundary-tone="green"
    :boundary-rows="[]"
    right-title="规则与业务配置"
    :right-cards="rightCards"
    workspace-mode="wide"
    right-panel-mode="drawer"
    right-toggle-label="升级说明"
    right-collapsed-default
    boundary-collapsed-default
    search-scope="admin"
    task-area="admin"
  >
    <section class="updates-page" aria-labelledby="updates-heading" data-guide="admin-rule-updates">
      <ElCard shadow="never">
        <div class="heading-row">
          <div>
            <h2 id="updates-heading">规则升级</h2>
            <p>项目建立时冻结了当时的业务规则。平台修好的规则，旧项目升级后才生效。</p>
          </div>
          <div class="heading-actions">
            <ElButton :loading="loading" @click="load">刷新</ElButton>
            <ElButton
              type="primary"
              :loading="applying"
              :disabled="!selected.some((row) => row.upgradable)"
              @click="apply"
              >升级选中项目</ElButton
            >
          </div>
        </div>
        <ElAlert v-if="loadError" type="error" :closable="false" :title="loadError" />
        <ElTable
          v-else
          v-loading="loading"
          :data="items"
          row-key="projectId"
          class="updates-table"
          @selection-change="(rows: BusinessPackUpdate[]) => (selected = rows)"
        >
          <template #empty><ElEmpty description="没有项目" /></template>
          <ElTableColumn
            type="selection"
            width="44"
            :selectable="(row: BusinessPackUpdate) => row.upgradable"
          />
          <ElTableColumn label="项目" min-width="200">
            <template #default="{ row }">
              <div class="project-name">{{ row.projectName || row.projectId }}</div>
              <small class="muted">{{ row.projectId }} · {{ row.projectStatus }}</small>
            </template>
          </ElTableColumn>
          <ElTableColumn label="规则版本" width="190">
            <template #default="{ row }">
              <ElTag v-if="row.upToDate" size="small" type="success"
                >已是最新 {{ row.currentVersion }}</ElTag
              >
              <ElTag v-else-if="row.archived" size="small" type="info">已归档，不能升级</ElTag>
              <span v-else>{{ row.frozenVersion || '旧版' }} → {{ row.currentVersion }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="改了什么" min-width="260">
            <template #default="{ row }">
              <small>{{ row.upToDate ? '—' : changeSummary(row) || '配置项有变化' }}</small>
            </template>
          </ElTableColumn>
          <ElTableColumn label="受影响节点" min-width="180">
            <template #default="{ row }">
              <small>{{ row.upToDate ? '—' : nodeSummary(row) }}</small>
            </template>
          </ElTableColumn>
          <ElTableColumn label="已有结论" width="96">
            <template #default="{ row }">{{
              row.upToDate ? '—' : row.affectedConclusionCount
            }}</template>
          </ElTableColumn>
        </ElTable>
      </ElCard>
    </section>
  </StaticPageShell>
</template>

<style scoped>
.updates-page {
  display: grid;
  gap: 16px;
}

.heading-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.heading-row h2 {
  margin: 0 0 4px;
  font-size: 18px;
}

.heading-row p,
.muted {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.heading-actions {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.project-name {
  font-weight: 600;
}
</style>
