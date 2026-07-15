<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ElAvatar,
  ElBadge,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElDescriptions,
  ElDescriptionsItem,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElInput,
  ElMenu,
  ElMenuItem,
  ElRadioButton,
  ElRadioGroup,
  ElSubMenu
} from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/store/modules/user'
import { Icon } from '@/components/Icon'
import type { OperationArea } from '@/types/aicheck'
import AuditStatusTag from './AuditStatusTag.vue'
import GlobalCommandPalette from './GlobalCommandPalette.vue'
import OperationTaskDrawer from './OperationTaskDrawer.vue'
import StaticShellRightPanel from './StaticShellRightPanel.vue'

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

type StaticShellTopStat = {
  key?: string
  label: string
  value?: string | number
  tone?: StaticShellTone
  clickable?: boolean
  title?: string
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
  topStats: ReadonlyArray<StaticShellTopStat>
  menuTitle: string
  menuRoot: string
  menuSections: ReadonlyArray<StaticShellMenuSection>
  peerNavTitle?: string
  peerNavItems?: ReadonlyArray<StaticShellMenuItem>
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
  searchScope?: OperationArea
  taskArea?: OperationArea
  projectId?: string
}>()
const emit = defineEmits<{
  (event: 'menu-select', item: StaticShellMenuItem): void
  (event: 'menu-search-change', value: string): void
  (event: 'menu-filter-change', value: string): void
  (event: 'top-stat-click', stat: StaticShellTopStat): void
}>()

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const rightPanelOpen = ref(!props.rightCollapsedDefault)
const rightPanelTriggerRef = ref<{ $el?: HTMLElement } | HTMLElement | null>(null)
const navigationOpen = ref(false)
const navigationTriggerRef = ref<{ $el?: HTMLElement } | HTMLElement | null>(null)
const treeFiltersOpen = ref(!props.menuFiltersCollapsedDefault)
const boundaryOpen = ref(!props.boundaryCollapsedDefault)
const commandPaletteRef = ref<InstanceType<typeof GlobalCommandPalette> | null>(null)
const taskDrawerRef = ref<InstanceType<typeof OperationTaskDrawer> | null>(null)
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
const peerNavTitleLabel = computed(() => props.peerNavTitle || '同级功能')
const menuSearchModel = computed({
  get: () => props.menuSearchValue || '',
  set: (value: string) => emit('menu-search-change', value)
})
const menuFilterModel = computed({
  get: () => props.menuFilterValue || props.menuFilters?.[0]?.value || '',
  set: (value: string) => emit('menu-filter-change', value)
})
const treeFilterPanels = computed<string[]>({
  get: () => (treeFiltersOpen.value ? ['filters'] : []),
  set: (panels) => {
    treeFiltersOpen.value = panels.includes('filters')
  }
})
const boundaryPanels = computed<string[]>({
  get: () => (boundaryOpen.value ? ['boundary'] : []),
  set: (panels) => {
    boundaryOpen.value = panels.includes('boundary')
  }
})
const userInitial = computed(() => props.userLabel.trim().slice(0, 1) || '用')
const elementTone = (tone: StaticShellTone = 'blue') => {
  const typeMap = {
    blue: 'primary',
    green: 'success',
    orange: 'warning',
    red: 'danger'
  } as const
  return typeMap[tone]
}

const staticMenuActiveIndex = computed(() => {
  for (const section of props.menuSections) {
    const activeItem = section.items.find((item) => item.route === route.path || item.active)
    if (activeItem) return getItemIndex(section, activeItem)
  }

  const firstSection = props.menuSections[0]
  const firstItem = firstSection?.items[0]
  return firstSection && firstItem ? getItemIndex(firstSection, firstItem) : ''
})

const hasExplicitActiveMenuItem = computed(() =>
  props.menuSections.some((section) =>
    section.items.some((item) => item.active || item.route === route.path)
  )
)

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
  navigationOpen.value = false
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

const isPeerNavItemActive = (item: StaticShellMenuItem) => {
  if (item.active) return true
  if (!item.route) return false
  return route.path === item.route || route.path.startsWith(`${item.route}/`)
}

const handlePeerNavSelect = (item: StaticShellMenuItem) => {
  navigationOpen.value = false
  emit('menu-select', item)
  if (item.route && item.route !== route.path) {
    router.push(item.route)
  }
}

const handleTopStatClick = (stat: StaticShellTopStat) => {
  if (stat.clickable) {
    emit('top-stat-click', stat)
  }
}

const focusRightPanelTrigger = () => {
  const target = rightPanelTriggerRef.value
  const element = target instanceof HTMLElement ? target : target?.$el
  element?.focus?.()
}

const focusNavigationTrigger = () => {
  const target = navigationTriggerRef.value
  const element = target instanceof HTMLElement ? target : target?.$el
  element?.focus?.()
}

const openRightPanel = () => {
  rightPanelOpen.value = true
}

const handleUserCommand = (command: string | number | object) => {
  if (command === 'logout') {
    userStore.logoutConfirm()
  }
}

const handleShellKeydown = (event: KeyboardEvent) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    commandPaletteRef.value?.open()
    return
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
          <div class="brand-mark">{{ brandMark }}</div>
          <div class="project-title">{{ title }}</div>
          <AuditStatusTag
            v-if="status"
            class="top-status"
            :tone="statusTone || 'blue'"
            size="default"
            round
          >
            {{ status }}
          </AuditStatusTag>
        </div>
        <ElButton
          class="global-search"
          aria-label="打开全局搜索"
          :title="`${searchPlaceholder}（⌘K）`"
          @click="commandPaletteRef?.open()"
        >
          <span>{{ searchPlaceholder }}</span
          ><kbd>⌘K</kbd>
        </ElButton>
        <div class="top-actions">
          <ElButton
            ref="navigationTriggerRef"
            class="mobile-navigation-trigger"
            plain
            aria-controls="aicheck-static-mobile-navigation"
            :aria-expanded="navigationOpen"
            @click="navigationOpen = true"
          >
            <Icon icon="vi-ep:menu" :size="17" />
            <span>导航</span>
          </ElButton>
          <ElBadge
            v-for="stat in topStats"
            :key="stat.key || stat.label"
            class="top-stat-badge"
            :value="stat.value"
            :hidden="stat.value === undefined"
            :type="elementTone(stat.tone || 'red')"
          >
            <ElButton
              v-if="stat.clickable"
              class="top-stat-item is-clickable"
              text
              :title="stat.title || `查看${stat.label}`"
              @click="handleTopStatClick(stat)"
            >
              {{ stat.label }}
            </ElButton>
            <span v-else class="top-stat-item">
              {{ stat.label }}
            </span>
          </ElBadge>
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
          <ElButton class="task-center-trigger" plain @click="taskDrawerRef?.open()">
            任务中心
          </ElButton>
          <ElDropdown trigger="click" class="user-menu" @command="handleUserCommand">
            <ElButton class="user" text aria-label="打开用户菜单">
              <ElAvatar class="avatar" :size="32">{{ userInitial }}</ElAvatar>
              <span>{{ userLabel }}</span>
              <Icon class="user-caret" icon="vi-ep:arrow-down" :size="12" />
            </ElButton>
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
        <aside id="aicheck-static-navigation" class="left">
          <section class="tree-wrap">
            <div class="section-title">
              <span>{{ menuTitle }}</span>
              <span class="section-tools">{{ menuSections.length }} 项</span>
            </div>
            <div v-if="peerNavItems?.length" class="peer-nav" :aria-label="peerNavTitleLabel">
              <div class="peer-nav-title">
                <span>{{ peerNavTitleLabel }}</span>
                <small>{{ peerNavItems.length }} 项</small>
              </div>
              <ElButton
                v-for="item in peerNavItems"
                :key="item.index"
                :class="['peer-nav-item', { active: isPeerNavItemActive(item) }]"
                text
                :title="item.hint ? `${item.label} · ${item.hint}` : item.label"
                :aria-current="isPeerNavItemActive(item) ? 'page' : undefined"
                @click="handlePeerNavSelect(item)"
              >
                <span class="peer-nav-marker" aria-hidden="true"></span>
                <span class="peer-nav-label">
                  <span>{{ item.label }}</span>
                  <small v-if="item.hint">{{ item.hint }}</small>
                </span>
                <AuditStatusTag v-if="item.badge" class="pill" :tone="item.tone || 'blue'" round>
                  {{ item.badge }}
                </AuditStatusTag>
                <span v-else></span>
              </ElButton>
            </div>
            <div v-if="hasMenuControls" class="tree-controls">
              <ElInput
                v-if="menuSearchPlaceholder"
                v-model="menuSearchModel"
                class="tree-search"
                :placeholder="menuSearchPlaceholder"
                :aria-label="menuSearchPlaceholder"
                clearable
              />
              <ElCollapse
                v-if="menuFilters?.length"
                v-model="treeFilterPanels"
                class="tree-filter-collapse"
              >
                <ElCollapseItem name="filters">
                  <template #title>
                    <span class="tree-filter-toggle">
                      <span>项目筛选</span>
                      <strong>{{ activeMenuFilterLabel }}</strong>
                      <em v-if="activeMenuFilter?.count !== undefined">
                        {{ activeMenuFilter.count }}
                      </em>
                    </span>
                  </template>
                  <ElRadioGroup v-model="menuFilterModel" class="tree-filter" aria-label="项目筛选">
                    <ElRadioButton
                      v-for="filter in menuFilters"
                      :key="filter.value"
                      :value="filter.value"
                    >
                      <span>{{ filter.label }}</span>
                      <em v-if="filter.count !== undefined">{{ filter.count }}</em>
                    </ElRadioButton>
                  </ElRadioGroup>
                </ElCollapseItem>
              </ElCollapse>
            </div>
            <ElEmpty
              v-if="!menuSections.length"
              class="tree-empty"
              :image-size="48"
              :description="menuEmptyText || '没有匹配的项目'"
            />
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
                        <AuditStatusTag
                          v-for="chip in section.chips"
                          :key="`${chip.label}-${chip.value}`"
                          class="tree-chip"
                          :tone="chip.tone || 'blue'"
                          round
                        >
                          {{ chip.label }} {{ chip.value }}
                        </AuditStatusTag>
                      </span>
                    </span>
                  </template>
                  <ElMenuItem
                    v-for="item in section.items"
                    :key="getItemIndex(section, item)"
                    :index="getItemIndex(section, item)"
                    :class="[
                      'tree-node',
                      {
                        active:
                          item.active ||
                          item.route === route.path ||
                          (!hasExplicitActiveMenuItem &&
                            getItemIndex(section, item) === staticMenuActiveIndex)
                      }
                    ]"
                    :title="item.hint ? `${item.label} · ${item.hint}` : item.label"
                    :aria-label="item.hint ? `${item.label}，${item.hint}` : item.label"
                    :aria-current="item.active || item.route === route.path ? 'page' : undefined"
                  >
                    <span class="tree-node-marker" aria-hidden="true"></span>
                    <span class="tree-label-wrap">
                      <span class="tree-label">{{ item.label }}</span>
                      <span v-if="item.hint" class="sr-only">{{ item.hint }}</span>
                    </span>
                    <AuditStatusTag
                      v-if="item.badge"
                      class="pill"
                      :tone="item.tone || 'blue'"
                      round
                    >
                      {{ item.badge }}
                    </AuditStatusTag>
                    <span v-else></span>
                  </ElMenuItem>
                </ElSubMenu>
              </ElSubMenu>
            </ElMenu>
          </section>

          <section :class="['node-files', { collapsed: !boundaryOpen }]">
            <ElCollapse v-model="boundaryPanels" class="boundary-collapse">
              <ElCollapseItem name="boundary">
                <template #title>
                  <span class="node-file-head">
                    <span>{{ boundaryTitle }}</span>
                    <span class="node-file-head-actions">
                      <AuditStatusTag class="pill" :tone="boundaryTone || 'green'" round>
                        {{ boundaryBadge }}
                      </AuditStatusTag>
                    </span>
                  </span>
                </template>
                <ElDescriptions
                  class="boundary-descriptions"
                  :column="1"
                  size="small"
                  :aria-label="boundaryTitle"
                >
                  <ElDescriptionsItem
                    v-for="row in boundaryRows"
                    :key="row.label"
                    :label="row.label"
                  >
                    {{ row.value }}
                  </ElDescriptionsItem>
                </ElDescriptions>
              </ElCollapseItem>
            </ElCollapse>
          </section>
        </aside>

        <main id="aicheck-static-main" class="center" tabindex="-1">
          <slot></slot>
        </main>

        <aside
          v-if="!rightPanelIsDrawer"
          id="static-right-panel"
          class="right"
          role="complementary"
          :aria-label="rightTitle"
        >
          <StaticShellRightPanel
            :title="rightTitle"
            :subtitle="rightSubtitle"
            :cards="rightCards"
          />
        </aside>
      </div>
      <ElDrawer
        v-model="navigationOpen"
        class="static-shell-navigation-drawer"
        modal-class="static-shell-navigation-overlay"
        :title="menuTitle"
        direction="ltr"
        size="min(340px, calc(100vw - 32px))"
        append-to-body
        destroy-on-close
        @closed="focusNavigationTrigger"
      >
        <nav
          id="aicheck-static-mobile-navigation"
          class="mobile-shell-navigation"
          :aria-label="menuTitle"
        >
          <div v-if="peerNavItems?.length" class="peer-nav" :aria-label="peerNavTitleLabel">
            <div class="peer-nav-title">
              <span>{{ peerNavTitleLabel }}</span>
              <small>{{ peerNavItems.length }} 项</small>
            </div>
            <ElButton
              v-for="item in peerNavItems"
              :key="item.index"
              :class="['peer-nav-item', { active: isPeerNavItemActive(item) }]"
              text
              :aria-current="isPeerNavItemActive(item) ? 'page' : undefined"
              @click="handlePeerNavSelect(item)"
            >
              <span class="peer-nav-marker" aria-hidden="true"></span>
              <span class="peer-nav-label">
                <span>{{ item.label }}</span>
                <small v-if="item.hint">{{ item.hint }}</small>
              </span>
              <AuditStatusTag v-if="item.badge" class="pill" :tone="item.tone || 'blue'" round>
                {{ item.badge }}
              </AuditStatusTag>
            </ElButton>
          </div>

          <div v-if="hasMenuControls" class="tree-controls mobile-tree-controls">
            <ElInput
              v-if="menuSearchPlaceholder"
              v-model="menuSearchModel"
              class="tree-search"
              :placeholder="menuSearchPlaceholder"
              :aria-label="menuSearchPlaceholder"
              clearable
            />
            <ElRadioGroup
              v-if="menuFilters?.length"
              v-model="menuFilterModel"
              class="tree-filter"
              aria-label="项目筛选"
            >
              <ElRadioButton
                v-for="filter in menuFilters"
                :key="filter.value"
                :value="filter.value"
              >
                <span>{{ filter.label }}</span>
                <em v-if="filter.count !== undefined">{{ filter.count }}</em>
              </ElRadioButton>
            </ElRadioGroup>
          </div>

          <ElEmpty
            v-if="!menuSections.length"
            class="tree-empty"
            :image-size="48"
            :description="menuEmptyText || '没有匹配的项目'"
          />
          <ElMenu
            v-else
            :key="`mobile-${staticMenuActiveIndex}`"
            class="mobile-static-menu"
            :default-active="staticMenuActiveIndex"
            :default-openeds="staticMenuDefaultOpeneds.slice(1)"
            :unique-opened="true"
            :collapse-transition="false"
            @select="handleStaticMenuSelect"
          >
            <ElSubMenu
              v-for="section in menuSections"
              :key="getSectionIdentity(section)"
              :index="getSectionIndex(section)"
            >
              <template #title>
                <span class="mobile-menu-section-title">
                  <strong>{{ section.title }}</strong>
                  <small>{{ section.meta }}</small>
                </span>
              </template>
              <ElMenuItem
                v-for="item in section.items"
                :key="getItemIndex(section, item)"
                :index="getItemIndex(section, item)"
              >
                <span class="tree-node-marker" aria-hidden="true"></span>
                <span class="tree-label">{{ item.label }}</span>
                <AuditStatusTag v-if="item.badge" class="pill" :tone="item.tone || 'blue'" round>
                  {{ item.badge }}
                </AuditStatusTag>
              </ElMenuItem>
            </ElSubMenu>
          </ElMenu>

          <ElCollapse v-model="boundaryPanels" class="mobile-boundary">
            <ElCollapseItem name="boundary">
              <template #title>
                <span class="mobile-boundary-title">
                  <span>{{ boundaryTitle }}</span>
                  <AuditStatusTag :tone="boundaryTone || 'green'" round>
                    {{ boundaryBadge }}
                  </AuditStatusTag>
                </span>
              </template>
              <ElDescriptions class="mobile-boundary-descriptions" :column="1" size="small">
                <ElDescriptionsItem v-for="row in boundaryRows" :key="row.label" :label="row.label">
                  {{ row.value }}
                </ElDescriptionsItem>
              </ElDescriptions>
            </ElCollapseItem>
          </ElCollapse>
        </nav>
      </ElDrawer>
      <ElDrawer
        v-if="rightPanelIsDrawer"
        v-model="rightPanelOpen"
        class="static-shell-right-drawer"
        modal-class="static-shell-right-overlay"
        :title="rightTitle"
        direction="rtl"
        size="min(420px, calc(100vw - 32px))"
        append-to-body
        destroy-on-close
        @closed="focusRightPanelTrigger"
      >
        <StaticShellRightPanel title="" :subtitle="rightSubtitle" :cards="rightCards" />
      </ElDrawer>
      <GlobalCommandPalette
        ref="commandPaletteRef"
        :scope="searchScope || 'workbench'"
        :project-id="projectId"
        :placeholder="searchPlaceholder"
      />
      <OperationTaskDrawer
        ref="taskDrawerRef"
        :area="taskArea || searchScope || 'workbench'"
        :project-id="projectId"
      />
    </div>
  </div>
</template>

<style scoped>
.aicheck-static-viewport {
  --bg: var(--aicheck-bg, #eef3f8);
  --panel: var(--aicheck-surface, #fff);
  --panel-soft: var(--aicheck-surface-soft, #f8fbff);
  --panel-muted: var(--aicheck-surface-muted, #f2f6fb);
  --line: var(--aicheck-border, #d4deeb);
  --line-soft: var(--aicheck-border-soft, #e5ecf6);
  --line-strong: var(--aicheck-border-strong, #c2d1e3);
  --head: var(--aicheck-surface-muted, #f2f6fb);
  --shadow-xs: var(--aicheck-shadow-xs, 0 1px 2px rgb(20 34 56 / 5%));
  --shadow-sm: var(--aicheck-shadow-sm, 0 6px 16px rgb(15 23 42 / 6%));
  --shadow-md: var(--aicheck-shadow-md, 0 14px 32px rgb(15 23 42 / 9%));
  --ink: var(--aicheck-text-strong, #172033);
  --muted: var(--aicheck-text-muted, #52647d);
  --blue: var(--aicheck-primary, #1f66d8);
  --blue-2: var(--aicheck-primary-strong, #174fa8);
  --blue-soft: var(--aicheck-active-bg, #edf5ff);
  --green: var(--aicheck-success, #087443);
  --green-soft: var(--aicheck-success-bg, #ecfdf3);
  --orange: var(--aicheck-warning, #8a4b00);
  --orange-soft: var(--aicheck-warning-bg, #fff7e6);
  --red: var(--aicheck-danger, #b42318);
  --red-soft: var(--aicheck-danger-bg, #fef3f2);

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
  font-weight: 600;
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
  outline: 0;
  opacity: 1;
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
  position: relative;
  z-index: 2;
  display: grid;
  min-width: 0;
  min-height: 68px;
  padding: 0 20px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  box-shadow: 0 8px 22px rgb(15 23 42 / 5%);
  grid-template-columns: minmax(220px, 360px) minmax(150px, 340px) minmax(0, max-content);
  gap: 14px;
  align-items: center;
}

.brand {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  min-width: 0;
}

.brand-mark {
  display: grid;
  width: 30px;
  height: 30px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(180deg, #4b86ff, #1761d2);
  border-radius: 8px;
  place-items: center;
}

.project-title {
  min-width: 0;
  overflow: hidden;
  font-size: 25px;
  font-weight: 600;
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
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  border: 1px solid transparent;
  border-radius: 5px;
}

.top-status {
  height: 32px;
  padding: 0 12px;
  border: 0;
}

.global-search {
  --el-button-bg-color: var(--panel-soft);
  --el-button-border-color: var(--line-strong);
  --el-button-hover-bg-color: var(--panel);
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
  color: var(--muted);
  text-align: left;
  cursor: pointer;
  background: var(--panel-soft);
  border: 1px solid var(--line-strong);
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
  display: flex;
  justify-content: flex-start;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.global-search kbd {
  display: inline-flex;
  min-width: 34px;
  min-height: 24px;
  padding: 2px 6px;
  margin-left: auto;
  font:
    500 12px/1 system-ui,
    sans-serif;
  color: #52647d;
  background: #fff;
  border: 1px solid #d4deeb;
  border-radius: 4px;
  align-items: center;
  justify-content: center;
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

.top-stat-item,
.right-panel-trigger,
.user-menu {
  flex: 0 0 auto;
}

.top-stat-badge {
  display: inline-flex;
  align-items: center;
}

.top-stat-badge :deep(.el-badge__content) {
  position: static;
  margin-left: -5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  border: 2px solid var(--panel);
  transform: none;
}

.top-stat-item {
  --el-button-text-color: #27364d;
  --el-button-hover-text-color: var(--blue-2);
  --el-button-hover-bg-color: #f4f8ff;

  display: inline-flex;
  min-height: 34px;
  padding: 0 10px;
  font: inherit;
  font-weight: 600;
  color: inherit;
  white-space: nowrap;
  background: transparent;
  border: 0;
  border-radius: 999px;
  align-items: center;
}

.top-stat-item.is-clickable {
  cursor: pointer;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    box-shadow 0.18s ease;
}

.top-stat-item.is-clickable:hover,
.top-stat-item.is-clickable:focus-visible {
  color: var(--blue-2);
  background: #f4f8ff;
  outline: 0;
  box-shadow: 0 0 0 3px rgb(31 102 216 / 12%);
}

.right-panel-trigger {
  --el-button-bg-color: var(--panel);
  --el-button-border-color: var(--line-strong);
  --el-button-hover-bg-color: #f4f8ff;
  --el-button-hover-border-color: #9db8df;
  --el-button-hover-text-color: var(--blue-2);

  min-height: 40px;
  font-weight: 600;
}

.task-center-trigger {
  min-height: 40px;
  font-weight: 600;
}

.mobile-navigation-trigger {
  display: none;
  min-height: 40px;
  font-weight: 600;
  gap: 6px;
}

.avatar {
  flex: 0 0 auto;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(180deg, #4b83f7, #1e5ec8);
}

.user-menu {
  flex: 0 0 auto;
}

.user {
  --el-button-text-color: #27364d;
  --el-button-hover-text-color: var(--blue-2);
  --el-button-hover-bg-color: #f4f8ff;

  display: inline-flex;
  min-height: 40px;
  padding: 0 8px 0 4px;
  font-weight: 600;
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

.user :deep(> span) {
  display: inline-flex;
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
  background: var(--panel-muted);
  border-right: 1px solid var(--line);
  grid-template-rows: minmax(0, 1fr) auto;
}

.shell-wide .center,
.shell-wide .right {
  padding: 18px 18px 24px;
}

.shell-wide .right {
  background: var(--panel-muted);
  border-left: 1px solid var(--line);
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
  background: var(--panel-muted);
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
  font-weight: 600;
}

.section-tools {
  font-size: 16px;
  color: #6e7d92;
}

.peer-nav {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 5px;
  padding: 0 12px 9px;
  margin: 0 0 4px;
  border-bottom: 1px solid #e8eef7;
}

.peer-nav-title {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 22px;
  padding: 0 4px;
  font-size: 12px;
  font-weight: 600;
  color: #6a7890;
}

.peer-nav-title small {
  font-size: 12px;
  font-weight: 600;
  color: #8a98ad;
}

.peer-nav-item {
  --el-button-text-color: #304158;
  --el-button-hover-text-color: var(--blue-2);
  --el-button-hover-bg-color: #f5f9ff;

  display: grid;
  grid-template-columns: 6px minmax(0, 1fr) auto;
  gap: 5px;
  align-items: center;
  width: 100%;
  min-height: 30px;
  padding: 5px 6px;
  font-size: 12px;
  font-weight: 600;
  color: #304158;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #e2ebf6;
  border-radius: 7px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}

.peer-nav-item :deep(> span) {
  display: contents;
}

.peer-nav-item + .peer-nav-item {
  margin-left: 0;
}

.peer-nav-item:hover,
.peer-nav-item:focus-visible {
  color: var(--blue-2);
  background: #f5f9ff;
  border-color: #bdd4f6;
  outline: 0;
  transform: translateY(-1px);
  box-shadow: 0 7px 18px rgb(37 99 235 / 8%);
}

.peer-nav-item.active {
  color: var(--blue-2);
  background: linear-gradient(180deg, #eff6ff, #e8f1ff);
  border-color: #a9c8ff;
  box-shadow: inset 3px 0 0 var(--blue);
}

.peer-nav-marker {
  display: inline-flex;
  place-self: center;
  width: 5px;
  height: 5px;
  background: #aab9cc;
  border-radius: 999px;
}

.peer-nav-item.active .peer-nav-marker {
  background: var(--blue);
  box-shadow: 0 0 0 4px rgb(63 125 240 / 12%);
}

.peer-nav-label {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.peer-nav-label span,
.peer-nav-label small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.peer-nav-label small {
  display: none;
}

.peer-nav-item .pill {
  max-width: 34px;
  min-height: 17px;
  padding: 2px 4px;
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
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

.tree-search :deep(.el-input__wrapper) {
  min-height: 38px;
}

.tree-filter-toggle {
  flex: 1;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  width: 100%;
  min-height: 34px;
  padding: 6px 8px;
  font-size: 12px;
  font-weight: 600;
  color: #40536d;
  cursor: inherit;
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

.tree-filter-collapse {
  --el-collapse-border-color: transparent;
  --el-collapse-header-bg-color: transparent;
  --el-collapse-content-bg-color: transparent;

  border: 0;
}

.tree-filter-collapse :deep(.el-collapse-item__header) {
  height: auto;
  min-height: 36px;
  padding: 0;
  border: 0;
}

.tree-filter-collapse :deep(.el-collapse-item__arrow) {
  margin: 0 8px 0 4px;
  color: var(--muted);
}

.tree-filter-collapse :deep(.el-collapse-item__wrap) {
  border: 0;
}

.tree-filter-collapse :deep(.el-collapse-item__content) {
  padding: 8px 0 0;
}

.tree-filter {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.tree-filter :deep(.el-radio-button) {
  width: 100%;
  min-width: 0;
}

.tree-filter :deep(.el-radio-button__inner) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 34px;
  padding: 6px 8px;
  font-size: 12px;
  border: 0;
  border-radius: 7px;
  box-shadow: 0 0 0 1px #e1e9f5;
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
  font-weight: 600;
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

.peer-nav + .tree.static-tree-menu,
.peer-nav + .tree-controls + .tree.static-tree-menu {
  height: auto;
  min-height: 0;
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
  padding: 7px;
  background: linear-gradient(180deg, rgb(255 255 255 / 96%), rgb(248 251 255 / 96%));
  border: 1px solid var(--line-soft);
  border-radius: 9px;
  box-shadow: var(--shadow-xs);
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
  font-weight: 600;
}

.tree-root {
  min-height: 40px;
  padding: 0 10px;
  color: #1e3a5f;
  background: #eef5ff;
  border: 1px solid #c7d8ef;
  box-shadow: var(--shadow-xs);
}

.tree-root > span:first-child,
.tree-group > span:first-child {
  display: inline-grid;
  align-items: center;
  justify-content: center;
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
  font-size: 12px;
  font-weight: 600;
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
  font-size: 12px;
  font-weight: 600;
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
  font-size: 12px;
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
  font-weight: 600;
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
  font-size: 12px;
  font-weight: 600;
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
  background: var(--panel);
  border-top: 1px solid var(--line);
}

.node-files.collapsed {
  max-height: 46px;
  overflow: hidden;
}

.node-file-head {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 44px;
  padding: 0 8px 0 18px;
  font-weight: 600;
  color: #172033;
  background: var(--panel);
  border: 0;
  transition:
    color 0.18s ease,
    background-color 0.18s ease;
}

.boundary-collapse {
  --el-collapse-border-color: transparent;
  --el-collapse-header-bg-color: var(--panel);
  --el-collapse-content-bg-color: var(--panel);

  border: 0;
}

.boundary-collapse :deep(.el-collapse-item__header) {
  height: auto;
  min-height: 44px;
  border-bottom: 1px solid #e7eef8;
}

.boundary-collapse :deep(.el-collapse-item__header:hover),
.boundary-collapse :deep(.el-collapse-item__header:focus-visible) {
  color: var(--blue-2);
  background: #f8fbff;
  outline: 0;
}

.boundary-collapse :deep(.el-collapse-item__arrow) {
  margin: 0 14px 0 4px;
  color: var(--muted);
}

.boundary-collapse :deep(.el-collapse-item__wrap) {
  border: 0;
}

.boundary-collapse :deep(.el-collapse-item__content) {
  padding: 0;
}

.node-file-head-actions {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.node-file-head-actions small {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
}

.boundary-descriptions {
  padding: 8px 14px 14px;
}

.boundary-descriptions :deep(.el-descriptions__body) {
  background: transparent;
}

.boundary-descriptions :deep(.el-descriptions__cell) {
  padding-bottom: 8px;
  font-size: 12px;
  line-height: 18px;
}

.boundary-descriptions :deep(.el-descriptions__label) {
  width: 76px;
  font-weight: 600;
  color: var(--muted);
}

.boundary-descriptions :deep(.el-descriptions__content) {
  color: var(--ink);
  overflow-wrap: anywhere;
}

.center {
  height: 100%;
  min-width: 0;
  padding: 18px 20px 24px;
  overflow: hidden auto;
  background: var(--bg);
}

.right {
  height: 100%;
  min-width: 0;
  padding: 18px 20px 24px;
  overflow: hidden auto;
  background: var(--panel-muted);
  border-left: 1px solid var(--line);
}

:global(.static-shell-right-overlay) {
  top: 68px;
}

:global(.static-shell-right-drawer .el-drawer__body) {
  padding: 0 20px 24px;
}

:global(.static-shell-navigation-drawer .el-drawer__body) {
  padding: 0 12px 20px;
}

.mobile-shell-navigation {
  display: grid;
  min-width: 0;
  gap: 12px;
}

.mobile-shell-navigation .peer-nav {
  padding: 0 0 12px;
  margin: 0;
}

.mobile-tree-controls {
  padding: 0;
}

.mobile-static-menu {
  --el-menu-active-color: var(--blue-2);
  --el-menu-bg-color: transparent;
  --el-menu-hover-bg-color: #f4f8ff;

  border-right: 0;
}

.mobile-static-menu :deep(.el-sub-menu__title),
.mobile-static-menu :deep(.el-menu-item) {
  height: auto;
  min-height: 44px;
  border-radius: 9px;
}

.mobile-static-menu :deep(.el-menu-item) {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  gap: 8px;
  margin: 2px 0;
}

.mobile-static-menu :deep(.el-menu-item.is-active) {
  font-weight: 600;
  background: #edf5ff;
}

.mobile-menu-section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-width: 0;
  gap: 8px;
}

.mobile-menu-section-title strong {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
}

.mobile-menu-section-title small {
  flex: 0 0 auto;
  font-size: 12px;
  color: var(--muted);
}

.mobile-boundary {
  --el-collapse-border-color: transparent;
  --el-collapse-header-bg-color: #f7faff;
  --el-collapse-content-bg-color: #f7faff;

  padding: 0 4px;
  background: #f7faff;
  border-radius: 10px;
}

.mobile-boundary :deep(.el-collapse-item__header) {
  height: auto;
  min-height: 44px;
  padding: 0 8px;
  border: 0;
}

.mobile-boundary :deep(.el-collapse-item__wrap) {
  border: 0;
}

.mobile-boundary :deep(.el-collapse-item__content) {
  padding: 0 8px 12px;
}

.mobile-boundary-title {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding-right: 8px;
  font-size: 13px;
  font-weight: 600;
}

.mobile-boundary-descriptions :deep(.el-descriptions__body) {
  background: transparent;
}

.mobile-boundary-descriptions :deep(.el-descriptions__cell) {
  padding-bottom: 8px;
  font-size: 12px;
  line-height: 1.55;
}

.mobile-boundary-descriptions :deep(.el-descriptions__label) {
  width: 64px;
  font-weight: 600;
  color: var(--muted);
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
  font-weight: 600;
  color: #485a73;
  background: var(--head);
}

.table tbody tr:hover th,
.table tbody tr:hover td {
  background: var(--panel-soft);
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

@media (prefers-reduced-motion: reduce) {
  .global-search,
  .tree-node,
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
    max-width: 100%;
    padding-bottom: 2px;
    overflow-x: auto;
    flex-wrap: nowrap;
    white-space: nowrap;
    justify-content: flex-start;
    scrollbar-width: none;
  }

  .top-actions::-webkit-scrollbar {
    display: none;
  }

  .brand {
    grid-template-columns: 34px minmax(0, 1fr);
  }

  .top-status {
    grid-column: 2;
    justify-self: start;
  }

  .global-search,
  .shell-wide .global-search {
    width: 100%;
  }

  .left,
  .center,
  .right {
    min-height: auto;
  }

  .left {
    display: none;
  }

  .mobile-navigation-trigger {
    display: inline-flex;
  }

  .center,
  .right {
    height: auto;
    padding: 14px 12px 18px;
  }
}
</style>
