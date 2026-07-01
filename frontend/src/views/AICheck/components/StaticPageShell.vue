<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ElButton,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElMenu,
  ElMenuItem,
  ElSubMenu
} from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/store/modules/user'
import { Icon } from '@/components/Icon'

type StaticShellTone = 'blue' | 'green' | 'orange' | 'red'

type StaticShellMenuItem = {
  index: string
  label: string
  hint?: string
  badge?: string
  tone?: StaticShellTone
  active?: boolean
  route?: string
  projectId?: string
  subpage?: string
}

type StaticShellMenuSection = {
  id?: string
  title: string
  meta?: string
  defaultOpen?: boolean
  chips?: ReadonlyArray<{ label: string; value: string | number; tone?: StaticShellTone }>
  items: ReadonlyArray<StaticShellMenuItem>
}

type StaticShellMenuFilter = {
  label: string
  value: string
  count?: number
}

type StaticShellBoundaryRow = {
  label: string
  value: string
}

type StaticShellRightRow = {
  label: string
  value?: string
  valueBadge?: string
  valueTone?: StaticShellTone
  progress?: number
  progressTone?: StaticShellTone
}

type StaticShellTimelineRow = {
  title: string
  description: string
  tone?: StaticShellTone
}

type StaticShellRightCard = {
  title: string
  rows?: ReadonlyArray<StaticShellRightRow>
  timeline?: ReadonlyArray<StaticShellTimelineRow>
  note?: string
}

const props = defineProps<{
  brandMark: string
  title: string
  status?: string
  statusTone?: StaticShellTone
  searchPlaceholder: string
  userLabel: string
  topStats: ReadonlyArray<{ label: string; value?: string | number; tone?: StaticShellTone }>
  menuTitle: string
  menuRoot: string
  menuSections: ReadonlyArray<StaticShellMenuSection>
  menuSearchPlaceholder?: string
  menuSearchValue?: string
  menuFilters?: ReadonlyArray<StaticShellMenuFilter>
  menuFilterValue?: string
  menuFiltersCollapsedDefault?: boolean
  menuEmptyText?: string
  boundaryTitle: string
  boundaryBadge: string
  boundaryTone?: StaticShellTone
  boundaryRows: ReadonlyArray<StaticShellBoundaryRow>
  boundaryCollapsedDefault?: boolean
  rightTitle: string
  rightSubtitle?: string
  rightCards: ReadonlyArray<StaticShellRightCard>
  workspaceMode?: 'default' | 'wide'
  rightPanelMode?: 'inline' | 'drawer'
  rightCollapsedDefault?: boolean
  rightToggleLabel?: string
}>()
const emit = defineEmits<{
  (event: 'menu-select', item: StaticShellMenuItem): void
  (event: 'menu-search-change', value: string): void
  (event: 'menu-filter-change', value: string): void
}>()

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const rightPanelOpen = ref(!props.rightCollapsedDefault)
const rightPanelTriggerRef = ref<{ $el?: HTMLElement } | HTMLElement | null>(null)
const rightPanelCloseRef = ref<{ $el?: HTMLElement } | HTMLElement | null>(null)
const treeFiltersOpen = ref(!props.menuFiltersCollapsedDefault)
const boundaryOpen = ref(!props.boundaryCollapsedDefault)
const rightPanelIsDrawer = computed(() => props.rightPanelMode === 'drawer')
const getSectionIdentity = (section: StaticShellMenuSection) => section.id || section.title
const getSectionIndex = (section: StaticShellMenuSection) =>
  `section-${getSectionIdentity(section)}`
const getItemIndex = (section: StaticShellMenuSection, item: StaticShellMenuItem) =>
  `${getSectionIdentity(section)}-${item.index}`
const hasMenuControls = computed(
  () => Boolean(props.menuSearchPlaceholder) || Boolean(props.menuFilters?.length)
)
const activeMenuFilter = computed(() => {
  const value = props.menuFilterValue || props.menuFilters?.[0]?.value
  return props.menuFilters?.find((filter) => filter.value === value) || props.menuFilters?.[0]
})
const activeMenuFilterLabel = computed(() => activeMenuFilter.value?.label || '全部')

const staticMenuActiveIndex = computed(() => {
  for (const section of props.menuSections) {
    const activeItem = section.items.find((item) => item.route === route.path || item.active)
    if (activeItem) return getItemIndex(section, activeItem)
  }

  const firstSection = props.menuSections[0]
  const firstItem = firstSection?.items[0]
  return firstSection && firstItem ? getItemIndex(firstSection, firstItem) : ''
})

const staticMenuDefaultOpeneds = computed(() => {
  const opened = ['root']
  for (const section of props.menuSections) {
    if (section.defaultOpen) {
      opened.push(getSectionIndex(section))
    }
  }
  const activeSection =
    props.menuSections.find((section) =>
      section.items.some((item) => getItemIndex(section, item) === staticMenuActiveIndex.value)
    ) || props.menuSections[0]
  if (activeSection) {
    const activeSectionIndex = getSectionIndex(activeSection)
    if (!opened.includes(activeSectionIndex)) {
      opened.push(activeSectionIndex)
    }
  }
  return opened
})

const handleStaticMenuSelect = (index: string) => {
  for (const section of props.menuSections) {
    const item = section.items.find((menuItem) => getItemIndex(section, menuItem) === index)
    if (item) {
      emit('menu-select', item)
    }
    if (item?.route && item.route !== route.path) {
      router.push(item.route)
      return
    }
  }
}

const handleMenuSearchInput = (event: Event) => {
  emit('menu-search-change', (event.target as HTMLInputElement).value)
}

const handleMenuFilter = (value: string) => {
  emit('menu-filter-change', value)
}

const focusElementRef = (target: typeof rightPanelTriggerRef.value) => {
  const element = target instanceof HTMLElement ? target : target?.$el
  element?.focus?.()
}

const openRightPanel = () => {
  rightPanelOpen.value = true
  nextTick(() => focusElementRef(rightPanelCloseRef.value))
}

const closeRightPanel = () => {
  rightPanelOpen.value = false
  nextTick(() => focusElementRef(rightPanelTriggerRef.value))
}

const handleUserCommand = (command: string | number | object) => {
  if (command === 'logout') {
    userStore.logoutConfirm()
  }
}

const handleShellKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape' && rightPanelIsDrawer.value && rightPanelOpen.value) {
    closeRightPanel()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleShellKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleShellKeydown)
})
</script>

<template>
  <div
    :class="[
      'aicheck-static-viewport',
      `shell-${workspaceMode || 'default'}`,
      {
        'right-drawer-mode': rightPanelIsDrawer,
        'right-panel-open': rightPanelIsDrawer && rightPanelOpen
      }
    ]"
  >
    <div class="aicheck-page app-shell">
      <a class="skip-main" href="#aicheck-static-main">跳到主内容</a>
      <header class="topbar">
        <div class="brand">
          <div class="hamburger">≡</div>
          <div class="brand-mark">{{ brandMark }}</div>
          <div class="project-title">{{ title }}</div>
          <div v-if="status" :class="['top-status', `pill-${statusTone || 'blue'}`]">
            {{ status }}
          </div>
        </div>
        <ElButton class="global-search" aria-label="打开全局搜索" :title="searchPlaceholder">
          {{ searchPlaceholder }}
        </ElButton>
        <div class="top-actions">
          <span v-for="stat in topStats" :key="stat.label">
            {{ stat.label
            }}<span v-if="stat.value !== undefined" :class="['notice-dot', stat.tone || 'red']">
              {{ stat.value }}
            </span>
          </span>
          <ElButton
            v-if="rightPanelIsDrawer"
            ref="rightPanelTriggerRef"
            class="right-panel-trigger"
            plain
            aria-controls="static-right-panel"
            :aria-expanded="rightPanelOpen"
            @click="openRightPanel"
          >
            {{ rightToggleLabel || rightTitle }}
          </ElButton>
          <ElDropdown trigger="click" class="user-menu" @command="handleUserCommand">
            <button class="user" type="button" aria-label="打开用户菜单">
              <span class="avatar"></span>
              <span>{{ userLabel }}</span>
              <span class="user-caret">⌄</span>
            </button>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem disabled>{{ userLabel }}</ElDropdownItem>
                <ElDropdownItem command="logout" divided>退出登录</ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
        </div>
      </header>

      <div class="workspace">
        <aside class="left">
          <section class="tree-wrap">
            <div class="section-title">
              <span>{{ menuTitle }}</span>
              <span class="section-tools">{{ menuSections.length }} 项</span>
            </div>
            <div v-if="hasMenuControls" class="tree-controls">
              <label v-if="menuSearchPlaceholder" class="tree-search">
                <span class="sr-only">{{ menuSearchPlaceholder }}</span>
                <input
                  :value="menuSearchValue || ''"
                  :placeholder="menuSearchPlaceholder"
                  type="search"
                  autocomplete="off"
                  @input="handleMenuSearchInput"
                />
              </label>
              <button
                v-if="menuFilters?.length"
                class="tree-filter-toggle"
                type="button"
                :aria-expanded="treeFiltersOpen"
                @click="treeFiltersOpen = !treeFiltersOpen"
              >
                <span>项目筛选</span>
                <strong>{{ activeMenuFilterLabel }}</strong>
                <em v-if="activeMenuFilter?.count !== undefined">{{ activeMenuFilter.count }}</em>
                <small>{{ treeFiltersOpen ? '收起' : '展开' }}</small>
              </button>
              <div
                v-if="menuFilters?.length && treeFiltersOpen"
                class="tree-filter"
                aria-label="项目筛选"
              >
                <button
                  v-for="filter in menuFilters"
                  :key="filter.value"
                  type="button"
                  :class="{ active: (menuFilterValue || menuFilters[0]?.value) === filter.value }"
                  :aria-pressed="(menuFilterValue || menuFilters[0]?.value) === filter.value"
                  @click="handleMenuFilter(filter.value)"
                >
                  <span>{{ filter.label }}</span>
                  <em v-if="filter.count !== undefined">{{ filter.count }}</em>
                </button>
              </div>
            </div>
            <div v-if="!menuSections.length" class="tree-empty">
              {{ menuEmptyText || '没有匹配的项目' }}
            </div>
            <ElMenu
              v-else
              :key="staticMenuActiveIndex"
              class="tree static-tree-menu"
              :default-active="staticMenuActiveIndex"
              :default-openeds="staticMenuDefaultOpeneds"
              :unique-opened="true"
              :collapse-transition="false"
              @select="handleStaticMenuSelect"
            >
              <ElSubMenu index="root" class="tree-root-menu">
                <template #title>
                  <span class="tree-root" :title="menuRoot">
                    <span class="tree-root-caret" aria-hidden="true">
                      <Icon icon="vi-ep:arrow-down" :size="12" />
                    </span>
                    <span class="tree-label">{{ menuRoot }}</span>
                    <span></span>
                  </span>
                </template>
                <ElSubMenu
                  v-for="section in menuSections"
                  :key="getSectionIdentity(section)"
                  :index="getSectionIndex(section)"
                  class="tree-section-menu"
                >
                  <template #title>
                    <span
                      class="tree-group-wrap"
                      :title="section.meta ? `${section.title} · ${section.meta}` : section.title"
                    >
                      <span class="tree-group">
                        <span class="tree-group-caret" aria-hidden="true">
                          <Icon icon="vi-ep:arrow-down" :size="12" />
                        </span>
                        <span class="tree-group-title">{{ section.title }}</span>
                        <span class="tree-group-status">{{ section.meta }}</span>
                      </span>
                      <span v-if="section.chips?.length" class="tree-group-chips">
                        <span
                          v-for="chip in section.chips"
                          :key="`${chip.label}-${chip.value}`"
                          :class="['tree-chip', chip.tone || 'blue']"
                        >
                          {{ chip.label }} {{ chip.value }}
                        </span>
                      </span>
                    </span>
                  </template>
                  <ElMenuItem
                    v-for="item in section.items"
                    :key="getItemIndex(section, item)"
                    :index="getItemIndex(section, item)"
                    :class="['tree-node', { active: item.active }]"
                    :title="item.hint ? `${item.label} · ${item.hint}` : item.label"
                    :aria-label="item.hint ? `${item.label}，${item.hint}` : item.label"
                    :aria-current="item.active || item.route === route.path ? 'page' : undefined"
                  >
                    <span class="tree-node-marker" aria-hidden="true"></span>
                    <span class="tree-label-wrap">
                      <span class="tree-label">{{ item.label }}</span>
                      <span v-if="item.hint" class="sr-only">{{ item.hint }}</span>
                    </span>
                    <span v-if="item.badge" :class="['pill', item.tone || 'blue']">
                      {{ item.badge }}
                    </span>
                    <span v-else></span>
                  </ElMenuItem>
                </ElSubMenu>
              </ElSubMenu>
            </ElMenu>
          </section>

          <section :class="['node-files', { collapsed: !boundaryOpen }]">
            <button
              class="node-file-head"
              type="button"
              :aria-expanded="boundaryOpen"
              @click="boundaryOpen = !boundaryOpen"
            >
              <span>{{ boundaryTitle }}</span>
              <span class="node-file-head-actions">
                <span :class="['pill', boundaryTone || 'green']">{{ boundaryBadge }}</span>
                <small>{{ boundaryOpen ? '收起' : '展开' }}</small>
              </span>
            </button>
            <table v-if="boundaryOpen" class="table compact" :aria-label="boundaryTitle">
              <tbody>
                <tr v-for="row in boundaryRows" :key="row.label">
                  <th>{{ row.label }}</th>
                  <td>{{ row.value }}</td>
                </tr>
              </tbody>
            </table>
          </section>
        </aside>

        <main id="aicheck-static-main" class="center" tabindex="-1">
          <slot></slot>
        </main>

        <button
          v-if="rightPanelIsDrawer && rightPanelOpen"
          class="right-scrim"
          type="button"
          aria-label="收起右侧摘要"
          @click="closeRightPanel"
        ></button>

        <aside
          v-if="!rightPanelIsDrawer || rightPanelOpen"
          id="static-right-panel"
          class="right"
          :role="rightPanelIsDrawer ? 'dialog' : 'complementary'"
          :aria-modal="rightPanelIsDrawer ? 'true' : undefined"
          :aria-label="rightTitle"
        >
          <div class="right-panel-head">
            <h2 class="right-title">{{ rightTitle }}</h2>
            <ElButton
              v-if="rightPanelIsDrawer"
              ref="rightPanelCloseRef"
              class="right-panel-close"
              text
              :aria-label="`收起${rightTitle}`"
              @click="closeRightPanel"
            >
              收起
            </ElButton>
          </div>
          <div v-if="rightSubtitle" class="preview-name">{{ rightSubtitle }}</div>
          <section v-for="card in rightCards" :key="card.title" class="right-card">
            <h3>{{ card.title }}</h3>
            <div class="body">
              <table v-if="card.rows?.length" class="table compact" :aria-label="card.title">
                <tbody>
                  <tr v-for="row in card.rows" :key="row.label">
                    <th>{{ row.label }}</th>
                    <td>
                      <div v-if="row.progress !== undefined" class="shell-progress">
                        <span
                          :class="row.progressTone || 'blue'"
                          :style="{ width: `${row.progress}%` }"
                        ></span>
                      </div>
                      <template v-else>
                        <span v-if="row.value">{{ row.value }}</span>
                        <span
                          v-if="row.valueBadge"
                          :class="['pill inline-pill', row.valueTone || 'blue']"
                        >
                          {{ row.valueBadge }}
                        </span>
                      </template>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-if="card.timeline?.length" class="timeline" :aria-label="card.title">
                <div v-for="item in card.timeline" :key="item.title" class="time-row">
                  <span :class="['time-dot', item.tone || 'blue']"></span>
                  <div>
                    <strong>{{ item.title }}</strong
                    ><br />{{ item.description }}
                  </div>
                </div>
              </div>
              <div v-if="card.note" class="readonly-mask">{{ card.note }}</div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  </div>
</template>

<style scoped>
.aicheck-static-viewport {
  --bg: #f4f7fb;
  --panel: #fff;
  --line: #d9e2ef;
  --line-soft: #e9eef6;
  --head: #f3f6fa;
  --ink: #172033;
  --muted: #6a7890;
  --blue: #1f66d8;
  --blue-2: #0c56c2;
  --blue-soft: #eaf3ff;
  --green: #14a36b;
  --green-soft: #eaf8f1;
  --orange: #ff8a00;
  --orange-soft: #fff4e3;
  --red: #ff4d3d;
  --red-soft: #fff0ee;

  width: 100%;
  height: 100dvh;
  max-width: 100vw;
  min-height: 640px;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei',
    'Noto Sans CJK SC', Arial, sans-serif;
  color: var(--ink);
  background: var(--bg);
}

.aicheck-static-viewport *,
.aicheck-static-viewport *::before,
.aicheck-static-viewport *::after {
  box-sizing: border-box;
}

.skip-main {
  position: fixed;
  top: 10px;
  left: 10px;
  z-index: 7000;
  padding: 9px 12px;
  font-size: 13px;
  font-weight: 900;
  color: #0c56c2;
  text-decoration: none;
  pointer-events: none;
  background: #fff;
  border: 1px solid #a9c8ff;
  border-radius: 8px;
  opacity: 0;
  transform: translateY(-8px);
  transition:
    opacity 0.18s ease,
    transform 0.18s ease;
}

.skip-main:focus-visible {
  pointer-events: auto;
  opacity: 1;
  outline: 0;
  transform: translateY(0);
  box-shadow: 0 0 0 3px rgb(37 99 235 / 16%);
}

.app-shell {
  display: grid;
  width: 100%;
  height: 100dvh;
  max-width: 100vw;
  min-width: 0;
  min-height: 0;
  overflow-x: hidden;
  background: var(--bg);
  grid-template-rows: auto minmax(0, 1fr);
}

.topbar {
  display: grid;
  min-width: 0;
  min-height: 68px;
  padding: 0 20px;
  background: #fff;
  border-bottom: 1px solid var(--line);
  grid-template-columns: minmax(220px, 360px) minmax(150px, 340px) minmax(0, max-content);
  gap: 14px;
  align-items: center;
}

.brand {
  display: grid;
  grid-template-columns: 24px 34px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  min-width: 0;
}

.hamburger {
  font-size: 22px;
  line-height: 1;
  color: #304158;
}

.brand-mark {
  display: grid;
  width: 30px;
  height: 30px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(180deg, #4b86ff, #1761d2);
  border-radius: 8px;
  place-items: center;
}

.project-title {
  min-width: 0;
  overflow: hidden;
  font-size: 25px;
  font-weight: 800;
  line-height: 1.1;
  color: var(--ink);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.top-status,
.pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 3px 8px;
  font-size: 13px;
  font-weight: 800;
  line-height: 1;
  white-space: nowrap;
  border: 1px solid transparent;
  border-radius: 5px;
}

.top-status {
  height: 36px;
  padding: 0 14px;
}

.pill.blue,
.pill-blue {
  color: var(--blue-2);
  background: var(--blue-soft);
  border-color: #bcd4ff;
}

.pill.green,
.pill-green {
  color: var(--green);
  background: var(--green-soft);
  border-color: #bdebd1;
}

.pill.orange,
.pill-orange {
  color: var(--orange);
  background: var(--orange-soft);
  border-color: #ffd399;
}

.pill.red,
.pill-red {
  color: var(--red);
  background: var(--red-soft);
  border-color: #ffc5bd;
}

.global-search {
  --el-button-bg-color: #fff;
  --el-button-border-color: #cbd8ea;
  --el-button-hover-bg-color: #f8fbff;
  --el-button-hover-border-color: #9db8df;
  --el-button-hover-text-color: #52647d;
  --el-button-active-bg-color: #eef5ff;
  --el-button-active-border-color: #8fb0df;
  --el-button-active-text-color: #52647d;

  display: flex;
  width: min(340px, 100%);
  height: 40px;
  padding: 0 16px;
  margin: 0;
  font-weight: 600;
  color: #8b98aa;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #cbd8ea;
  border-radius: 6px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
  align-items: center;
  justify-content: flex-start;
  justify-self: center;
}

.global-search :deep(span) {
  justify-content: flex-start;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.global-search:hover,
.global-search:focus-visible {
  color: #52647d;
  background: #f8fbff;
  border-color: #9db8df;
  outline: 0;
  box-shadow: 0 0 0 3px rgb(31 102 216 / 12%);
}

.top-actions {
  display: flex;
  min-width: 0;
  font-size: 14px;
  color: #27364d;
  white-space: nowrap;
  gap: 10px;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: nowrap;
}

.top-actions > span,
.right-panel-trigger,
.user-menu {
  flex: 0 0 auto;
}

.right-panel-trigger {
  --el-button-bg-color: #fff;
  --el-button-border-color: #cbd8ea;
  --el-button-hover-bg-color: #f4f8ff;
  --el-button-hover-border-color: #9db8df;
  --el-button-hover-text-color: var(--blue-2);

  min-height: 40px;
  font-weight: 800;
}

.notice-dot {
  display: inline-flex;
  height: 22px;
  min-width: 22px;
  padding: 0 6px;
  margin-left: 2px;
  font-size: 12px;
  font-weight: 800;
  color: #fff;
  background: #ef3f3b;
  border-radius: 999px;
  align-items: center;
  justify-content: center;
}

.notice-dot.blue {
  background: var(--blue);
}

.notice-dot.green {
  background: var(--green);
}

.notice-dot.orange {
  background: var(--orange);
}

.avatar {
  width: 32px;
  height: 32px;
  background: linear-gradient(180deg, #4b83f7, #1e5ec8);
  border-radius: 50%;
}

.user-menu {
  flex: 0 0 auto;
}

.user {
  display: inline-flex;
  min-height: 40px;
  padding: 0 8px 0 4px;
  font-weight: 700;
  color: inherit;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 999px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    box-shadow 0.18s ease;
  gap: 8px;
  align-items: center;
}

.user:hover,
.user:focus-visible {
  color: var(--blue-2);
  background: #f4f8ff;
  outline: 0;
  box-shadow: 0 0 0 3px rgb(31 102 216 / 12%);
}

.user-caret {
  font-size: 12px;
  line-height: 1;
  color: #6a7890;
}

.workspace {
  position: relative;
  display: grid;
  width: 100%;
  height: 100%;
  max-width: 100vw;
  min-height: 0;
  overflow-x: hidden;
  grid-template-columns: minmax(300px, 404px) minmax(0, 1fr) minmax(320px, 552px);
}

.right-drawer-mode .workspace,
.right-drawer-mode.shell-wide .workspace {
  grid-template-columns: minmax(248px, 300px) minmax(0, 1fr);
}

.shell-wide .topbar {
  grid-template-columns: minmax(220px, 300px) minmax(160px, 360px) max-content;
}

.shell-wide .workspace {
  grid-template-columns: minmax(248px, 300px) minmax(0, 1fr) minmax(260px, 340px);
}

.shell-wide .left {
  background: #f8fafc;
  border-right: 0;
  grid-template-rows: minmax(0, 1fr) auto;
}

.shell-wide .center,
.shell-wide .right {
  padding: 18px 18px 24px;
}

.shell-wide .right {
  background: #f8fafc;
  border-left: 0;
}

.shell-wide .tree.static-tree-menu {
  border-bottom-color: #e8eef7;
}

.shell-wide .tree-node {
  min-height: 42px;
  padding: 8px 10px;
}

.shell-wide .tree-node.active,
.shell-wide .tree-node.is-active {
  box-shadow: none;
}

.shell-wide .global-search {
  width: min(260px, 100%);
}

.shell-wide .node-files {
  max-height: 214px;
  border-top: 1px solid #e6edf7;
}

.shell-wide .node-file-head {
  min-height: 42px;
  padding: 0 14px;
}

.shell-wide .node-file-head > span:first-child {
  font-size: 15px;
}

.shell-wide .node-files .table.compact th,
.shell-wide .node-files .table.compact td {
  padding: 8px 10px;
  font-size: 12px;
  line-height: 18px;
}

.left,
.center,
.right {
  min-height: 0;
}

.center:focus {
  outline: none;
}

.left {
  display: grid;
  height: 100%;
  overflow: hidden auto;
  background: #fff;
  border-right: 1px solid var(--line);
  grid-template-rows: minmax(560px, 1fr) 394px;
}

.tree-wrap,
.node-files {
  min-height: 0;
  overflow: hidden auto;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 44px;
  padding: 0 18px;
  font-size: 18px;
  font-weight: 800;
}

.section-tools {
  font-size: 16px;
  color: #6e7d92;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.tree-controls {
  display: grid;
  gap: 8px;
  padding: 0 14px 8px;
}

.tree-search {
  display: block;
  min-width: 0;
}

.tree-search input {
  width: 100%;
  height: 38px;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 600;
  color: #26364e;
  background: #f8fbff;
  border: 1px solid #dce6f4;
  border-radius: 8px;
  outline: 0;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    background-color 0.18s ease;
}

.tree-search input::placeholder {
  color: #8a98ad;
}

.tree-search input:focus {
  background: #fff;
  border-color: #8eb8ff;
  box-shadow: 0 0 0 3px rgb(37 99 235 / 12%);
}

.tree-filter-toggle {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  gap: 8px;
  align-items: center;
  width: 100%;
  min-height: 34px;
  padding: 6px 8px;
  font-size: 12px;
  font-weight: 800;
  color: #40536d;
  cursor: pointer;
  background: linear-gradient(180deg, #fff, #f6f9fd);
  border: 1px solid #dce6f4;
  border-radius: 8px;
  transition:
    color 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    background-color 0.18s ease;
}

.tree-filter-toggle:hover,
.tree-filter-toggle:focus-visible {
  color: var(--blue-2);
  border-color: #a9c8ff;
  outline: 0;
  box-shadow: 0 6px 14px rgb(37 99 235 / 8%);
}

.tree-filter-toggle strong {
  min-width: 0;
  overflow: hidden;
  color: #18304f;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-filter-toggle em {
  min-width: 22px;
  padding: 2px 6px;
  font-style: normal;
  font-variant-numeric: tabular-nums;
  color: #2563eb;
  text-align: center;
  background: #eaf2ff;
  border-radius: 999px;
}

.tree-filter-toggle small {
  color: #6e7d92;
}

.tree-filter {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.tree-filter button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  min-height: 30px;
  padding: 6px 7px;
  font-size: 11.5px;
  font-weight: 800;
  color: #52627a;
  cursor: pointer;
  background: #fff;
  border: 1px solid #e1e9f5;
  border-radius: 8px;
  transition:
    color 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    background-color 0.18s ease;
}

.tree-filter button:hover,
.tree-filter button:focus-visible,
.tree-filter button.active {
  color: var(--blue-2);
  background: #f4f8ff;
  border-color: #a9c8ff;
  outline: 0;
  box-shadow: 0 6px 14px rgb(37 99 235 / 8%);
}

.tree-filter span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-filter em {
  flex: 0 0 auto;
  min-width: 22px;
  padding: 2px 6px;
  margin-left: 6px;
  font-style: normal;
  font-variant-numeric: tabular-nums;
  color: #2563eb;
  text-align: center;
  background: #eaf2ff;
  border-radius: 999px;
}

.tree-empty {
  display: grid;
  min-height: 120px;
  padding: 18px;
  margin: 8px 18px 16px;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.6;
  color: #64748b;
  text-align: center;
  background: #f8fbff;
  border: 1px dashed #c8d8ed;
  border-radius: 8px;
  place-items: center;
}

.tree.static-tree-menu {
  --el-menu-active-color: var(--blue-2);
  --el-menu-bg-color: transparent;
  --el-menu-hover-bg-color: transparent;
  --el-menu-text-color: #26364e;

  height: calc(100% - 44px);
  padding: 8px 10px 14px;
  overflow: auto;
  background: transparent;
  border-right: 0;
  border-bottom: 1px solid var(--line);
  scrollbar-width: thin;
  scrollbar-color: #c7d5e8 transparent;
}

.tree-controls + .tree.static-tree-menu {
  height: calc(100% - 104px);
}

.static-tree-menu :deep(.el-menu) {
  background: transparent;
  border-right: 0;
}

.static-tree-menu :deep(.el-sub-menu__title),
.static-tree-menu :deep(.el-menu-item) {
  height: auto;
  min-height: 36px;
  padding: 0 !important;
  line-height: 1.2;
  background: transparent;
}

.static-tree-menu :deep(.el-sub-menu__title:hover),
.static-tree-menu :deep(.el-menu-item:hover),
.static-tree-menu :deep(.el-menu-item:focus) {
  background: transparent;
}

.static-tree-menu :deep(.el-sub-menu__icon-arrow) {
  display: none !important;
}

.tree-root-menu,
.tree-section-menu {
  min-width: 0;
}

.tree-root-menu :deep(> .el-sub-menu__title) {
  margin: 0 0 8px;
}

.tree-section-menu {
  position: relative;
  margin: 6px 0;
}

.tree-section-menu::before {
  display: none;
}

.tree-section-menu :deep(> .el-sub-menu__title) {
  border-radius: 10px;
}

.tree-section-menu :deep(> .el-sub-menu__title:hover) {
  background: transparent;
}

.tree-root,
.tree-group,
.tree-node {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  min-height: 36px;
  color: #26364e;
  border-radius: 10px;
}

.tree-group-wrap {
  display: grid;
  width: 100%;
  min-width: 0;
  padding: 7px 7px;
  background: linear-gradient(180deg, rgb(255 255 255 / 92%), rgb(248 251 255 / 92%)),
    radial-gradient(circle at 16px 12px, rgb(37 99 235 / 8%), transparent 42px);
  border: 1px solid #e4ecf7;
  border-radius: 9px;
  box-shadow: 0 6px 16px rgb(15 23 42 / 4%);
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
  gap: 4px;
}

.tree-section-menu :deep(> .el-sub-menu__title:hover) .tree-group-wrap {
  border-color: #c9dcfb;
  transform: translateY(-1px);
  box-shadow: 0 12px 26px rgb(30 93 180 / 9%);
}

.tree-root,
.tree-group {
  font-weight: 800;
}

.tree-root {
  min-height: 40px;
  padding: 0 10px;
  color: #1e3a5f;
  background: #eef5ff;
  border: 1px solid #d4e3f8;
}

.tree-root > span:first-child,
.tree-group > span:first-child {
  display: inline-grid;
  align-items: center;
  justify-content: center;
  place-items: center;
  place-self: center;
  width: 22px;
  height: 22px;
  font-size: 12px;
  line-height: 1;
  color: #58708e;
  background: #fff;
  border: 1px solid #d5e1f0;
  border-radius: 7px;
}

.tree-root-caret,
.tree-group-caret {
  display: inline-grid;
  align-items: center;
  justify-content: center;
  place-items: center;
  place-self: center;
  line-height: 1;
  transform: none;
}

.tree-root-caret :deep(.el-icon),
.tree-group-caret :deep(.el-icon),
.tree-root-caret :deep(svg),
.tree-group-caret :deep(svg) {
  display: block;
  width: 12px;
  height: 12px;
  line-height: 1;
}

.tree-root > .tree-label {
  font-size: 13px;
  letter-spacing: 0;
  text-transform: none;
}

.tree-group {
  min-height: 26px;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  gap: 7px;
}

.tree-group-caret {
  display: inline-grid;
  align-items: center;
  justify-content: center;
  place-items: center;
  place-self: center;
  width: 20px;
  height: 20px;
  font-size: 12px;
  line-height: 1;
  color: #58708e;
  background: #fff;
  border: 1px solid #d5e1f0;
  border-radius: 7px;
}

.tree-group-title {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  line-height: 1.25;
  color: #182437;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-group-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  max-width: 84px;
  min-height: 22px;
  padding: 2px 6px;
  overflow: hidden;
  font-size: 11px;
  font-weight: 800;
  color: #415876;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: #f5f8fc;
  border: 1px solid #dfe8f5;
  border-radius: 999px;
}

.tree-group-chips {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, max-content));
  gap: 4px;
  padding: 0 0 0 27px;
  justify-content: start;
}

.tree-chip {
  display: inline-flex;
  max-width: 100%;
  min-height: 21px;
  padding: 2px 6px;
  overflow: hidden;
  font-size: 10.5px;
  font-weight: 800;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid transparent;
  border-radius: 999px;
  align-items: center;
  justify-content: center;
}

.tree-chip.blue {
  color: var(--blue-2);
  background: var(--blue-soft);
  border-color: #c8daf8;
}

.tree-chip.green {
  color: var(--green);
  background: var(--green-soft);
  border-color: #c4ecd7;
}

.tree-chip.orange {
  color: var(--orange);
  background: var(--orange-soft);
  border-color: #ffd9a6;
}

.tree-chip.red {
  color: var(--red);
  background: var(--red-soft);
  border-color: #ffc9c2;
}

.tree-node {
  position: relative;
  grid-template-columns: 7px minmax(0, 1fr) auto;
  min-height: 32px;
  padding: 5px 12px;
  margin: 0;
  font-weight: 600;
  border: 1px solid transparent;
  border-radius: 7px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    border-color 0.18s ease,
    transform 0.18s ease,
    box-shadow 0.18s ease;
}

.tree-section-menu :deep(> .el-menu.el-menu--inline) {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 2px;
  padding: 4px 0 6px 20px;
  overflow: visible;
}

.tree-section-menu :deep(> .el-menu.el-menu--inline > .el-menu-item) {
  width: 100%;
}

.tree-section-menu :deep(.el-menu-item.tree-node) {
  padding: 5px 12px !important;
}

.shell-wide .tree-section-menu :deep(.el-menu-item.tree-node) {
  padding: 8px 12px !important;
}

.tree-node::before,
.tree-node::after {
  position: absolute;
  pointer-events: none;
  content: '';
}

.tree-node::before {
  top: -3px;
  bottom: -3px;
  left: -11px;
  border-left: 1px solid #d8e5f5;
}

.tree-node::after {
  top: 50%;
  left: -11px;
  width: 10px;
  border-top: 1px solid #d8e5f5;
}

.tree-node-marker {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  place-self: center;
  width: 5px;
  height: 5px;
  background: #aab9cc;
  border-radius: 999px;
}

.tree-node .pill {
  min-height: 18px;
  padding: 2px 5px;
  font-size: 10px;
}

.tree-node:hover,
.tree-node:focus-visible,
.tree-node.is-active {
  color: var(--blue-2);
  background: #f5f9ff;
  border-color: #d7e6fb;
  outline: 0;
  transform: translateY(-1px);
}

.tree-node.active,
.tree-node.is-active {
  font-weight: 800;
  color: var(--blue-2);
  background: linear-gradient(180deg, #eff6ff, #e8f1ff);
  border-color: #bad2f7;
  box-shadow:
    inset 3px 0 0 var(--blue),
    0 8px 18px rgb(37 99 235 / 10%);
}

.tree-node.active > span:first-child,
.tree-node.is-active > span:first-child {
  background: linear-gradient(180deg, #3f7df0, #1f66d8);
  box-shadow: 0 0 0 4px rgb(63 125 240 / 12%);
}

.tree-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tree-label-wrap {
  display: grid;
  min-width: 0;
  gap: 0;
}

.tree-label-wrap small {
  min-width: 0;
  overflow: hidden;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.25;
  color: #718096;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-node.active .tree-label-wrap small,
.tree-node.is-active .tree-label-wrap small {
  color: #3568b7;
}

.node-files {
  background: #fff;
  border-top: 1px solid var(--line);
}

.node-files.collapsed {
  max-height: 46px;
  overflow: hidden;
}

.node-file-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 44px;
  padding: 0 18px;
  font-weight: 800;
  color: #172033;
  cursor: pointer;
  background: #fff;
  border: 0;
  border-bottom: 1px solid #e7eef8;
  transition:
    color 0.18s ease,
    background-color 0.18s ease;
}

.node-file-head:hover,
.node-file-head:focus-visible {
  color: var(--blue-2);
  background: #f8fbff;
  outline: 0;
}

.node-file-head-actions {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.node-file-head-actions small {
  font-size: 12px;
  font-weight: 800;
  color: #6e7d92;
}

.center {
  height: 100%;
  min-width: 0;
  padding: 18px 20px 24px;
  overflow: hidden auto;
}

.right {
  height: 100%;
  min-width: 0;
  padding: 18px 20px 24px;
  overflow: hidden auto;
  background: #fff;
  border-left: 1px solid var(--line);
}

.right-drawer-mode .right {
  position: fixed;
  top: 68px;
  right: 0;
  bottom: 0;
  z-index: 52;
  width: min(420px, calc(100vw - 32px));
  height: auto;
  padding: 18px 20px 24px;
  border-left: 1px solid var(--line);
  box-shadow: -20px 0 42px rgb(15 23 42 / 16%);
}

.right-scrim {
  position: fixed;
  inset: 68px 0 0;
  z-index: 50;
  cursor: pointer;
  background: rgb(15 23 42 / 28%);
  border: 0;
}

.right-panel-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
}

.right-panel-close {
  flex: 0 0 auto;
  min-height: 36px;
  font-weight: 800;
}

.right-title {
  margin: 0 0 8px;
  font-size: 21px;
  line-height: 1.2;
}

.preview-name {
  margin-bottom: 12px;
  font-weight: 800;
  color: #26364e;
}

.right-card {
  margin-top: 12px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 6px;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.right-card:hover,
.right-card:focus-within {
  border-color: #c4d5ee;
  box-shadow: 0 2px 8px rgb(20 34 56 / 8%);
}

.right-card h3 {
  padding: 13px 16px;
  margin: 0;
  font-size: 18px;
  line-height: 1.2;
  border-bottom: 1px solid var(--line-soft);
}

.right-card .body {
  padding: 14px 16px;
}

.table {
  width: 100%;
  font-size: 14px;
  border-collapse: collapse;
  table-layout: fixed;
}

.table th,
.table td {
  padding: 10px 11px;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  vertical-align: middle;
  border: 1px solid var(--line-soft);
  transition: background-color 0.18s ease;
}

.table th {
  font-weight: 900;
  color: #485a73;
  background: var(--head);
}

.table tbody tr:hover th,
.table tbody tr:hover td {
  background: #f4f8ff;
}

.table tr.selected th,
.table tr.selected td {
  background: var(--blue-soft);
}

.table.compact th,
.table.compact td {
  padding: 8px 9px;
  font-size: 13px;
}

.inline-pill {
  margin-left: 6px;
}

.shell-progress {
  height: 8px;
  overflow: hidden;
  background: #e6edf7;
  border-radius: 999px;
}

.shell-progress span {
  display: block;
  height: 100%;
  background: var(--blue);
  border-radius: inherit;
}

.shell-progress span.green {
  background: var(--green);
}

.shell-progress span.orange {
  background: var(--orange);
}

.shell-progress span.red {
  background: var(--red);
}

.timeline {
  display: grid;
  gap: 12px;
}

.time-row {
  display: grid;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
  color: #3f4f66;
  grid-template-columns: 14px minmax(0, 1fr);
  gap: 9px;
}

.time-row strong {
  font-size: 14px;
  font-weight: 900;
  color: var(--ink);
}

.time-dot {
  width: 10px;
  height: 10px;
  margin-top: 4px;
  background: var(--blue);
  border-radius: 50%;
  box-shadow: 0 0 0 4px var(--blue-soft);
}

.time-dot.green {
  background: var(--green);
  box-shadow: 0 0 0 4px var(--green-soft);
}

.time-dot.orange {
  background: var(--orange);
  box-shadow: 0 0 0 4px var(--orange-soft);
}

.time-dot.red {
  background: var(--red);
  box-shadow: 0 0 0 4px var(--red-soft);
}

.readonly-mask {
  padding: 12px;
  font-weight: 800;
  line-height: 1.6;
  color: #6b2b24;
  background: var(--red-soft);
  border: 1px solid #ffc5bd;
  border-radius: 6px;
}

@media (prefers-reduced-motion: reduce) {
  .global-search,
  .tree-node,
  .right-card,
  .table th,
  .table td {
    transition: none;
  }
}

@media (width <= 1360px) {
  .topbar {
    grid-template-columns: minmax(200px, 300px) minmax(160px, 360px) max-content;
    gap: 10px 14px;
  }

  .global-search {
    width: min(360px, 100%);
  }

  .top-actions {
    grid-column: auto;
    justify-content: flex-end;
    font-size: 14px;
    gap: 10px;
  }

  .workspace {
    grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  }

  .right-drawer-mode.shell-wide .workspace {
    grid-template-columns: minmax(260px, 300px) minmax(0, 1fr);
  }

  .right {
    grid-column: 1 / -1;
    min-height: auto;
    border-top: 1px solid var(--line);
    border-left: 0;
  }
}

@media (width <= 1180px) {
  .right-drawer-mode.shell-wide .workspace {
    grid-template-columns: 260px minmax(0, 1fr);
  }

  .shell-wide .topbar {
    grid-template-columns: minmax(190px, 260px) minmax(128px, 260px) max-content;
    gap: 12px;
    padding: 0 16px;
  }

  .shell-wide .global-search {
    width: min(260px, 100%);
  }
}

@media (width <= 900px) {
  .aicheck-static-viewport {
    height: auto;
    min-height: 100dvh;
    overflow-y: auto;
  }

  .app-shell {
    grid-template-rows: auto 1fr;
    height: auto;
    min-height: 100dvh;
  }

  .topbar,
  .workspace,
  .shell-wide .topbar,
  .shell-wide .workspace,
  .right-drawer-mode .workspace,
  .right-drawer-mode.shell-wide .workspace {
    grid-template-columns: minmax(0, 1fr);
  }

  .workspace {
    height: auto;
    overflow: visible;
  }

  .topbar {
    gap: 10px;
    min-height: 68px;
    padding: 10px 12px;
  }

  .top-actions {
    flex-wrap: wrap;
    white-space: normal;
    justify-content: flex-start;
  }

  .brand {
    grid-template-columns: 24px 34px minmax(0, 1fr);
  }

  .top-status {
    grid-column: 1 / -1;
    justify-self: start;
  }

  .left,
  .center,
  .right {
    min-height: auto;
  }

  .left {
    grid-template-rows: auto auto;
    height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .tree.static-tree-menu {
    max-height: 520px;
  }

  .center,
  .right {
    height: auto;
    padding: 14px 12px 18px;
  }
}
</style>
