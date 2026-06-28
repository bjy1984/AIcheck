<script setup lang="ts">
import { computed } from 'vue'
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

type StaticShellTone = 'blue' | 'green' | 'orange' | 'red'

type StaticShellMenuItem = {
  index: string
  label: string
  badge?: string
  tone?: StaticShellTone
  active?: boolean
  route?: string
}

type StaticShellMenuSection = {
  title: string
  meta?: string
  items: ReadonlyArray<StaticShellMenuItem>
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
  status: string
  statusTone?: StaticShellTone
  searchPlaceholder: string
  userLabel: string
  topStats: ReadonlyArray<{ label: string; value?: string | number; tone?: StaticShellTone }>
  menuTitle: string
  menuRoot: string
  menuSections: ReadonlyArray<StaticShellMenuSection>
  boundaryTitle: string
  boundaryBadge: string
  boundaryTone?: StaticShellTone
  boundaryRows: ReadonlyArray<StaticShellBoundaryRow>
  rightTitle: string
  rightSubtitle?: string
  rightCards: ReadonlyArray<StaticShellRightCard>
}>()

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const getSectionIndex = (section: StaticShellMenuSection) => `section-${section.title}`
const getItemIndex = (section: StaticShellMenuSection, item: StaticShellMenuItem) =>
  `${section.title}-${item.index}`

const staticMenuDefaultOpeneds = computed(() => [
  'root',
  ...props.menuSections.map((section) => getSectionIndex(section))
])

const staticMenuActiveIndex = computed(() => {
  for (const section of props.menuSections) {
    const activeItem = section.items.find((item) => item.route === route.path || item.active)
    if (activeItem) return getItemIndex(section, activeItem)
  }

  const firstSection = props.menuSections[0]
  const firstItem = firstSection?.items[0]
  return firstSection && firstItem ? getItemIndex(firstSection, firstItem) : ''
})

const handleStaticMenuSelect = (index: string) => {
  for (const section of props.menuSections) {
    const item = section.items.find((menuItem) => getItemIndex(section, menuItem) === index)
    if (item?.route && item.route !== route.path) {
      router.push(item.route)
      return
    }
  }
}

const handleUserCommand = (command: string | number | object) => {
  if (command === 'logout') {
    userStore.logoutConfirm()
  }
}
</script>

<template>
  <div class="aicheck-static-viewport">
    <div class="aicheck-page app-shell">
      <header class="topbar">
        <div class="brand">
          <div class="hamburger">≡</div>
          <div class="brand-mark">{{ brandMark }}</div>
          <div class="project-title">{{ title }}</div>
          <div :class="['top-status', `pill-${statusTone || 'blue'}`]">{{ status }}</div>
        </div>
        <ElButton class="global-search">{{ searchPlaceholder }}</ElButton>
        <div class="top-actions">
          <span v-for="stat in topStats" :key="stat.label">
            {{ stat.label
            }}<span v-if="stat.value !== undefined" :class="['notice-dot', stat.tone || 'red']">
              {{ stat.value }}
            </span>
          </span>
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
              <span class="section-tools">↻ ⚙</span>
            </div>
            <ElMenu
              class="tree static-tree-menu"
              :default-active="staticMenuActiveIndex"
              :default-openeds="staticMenuDefaultOpeneds"
              :collapse-transition="false"
              @select="handleStaticMenuSelect"
            >
              <ElSubMenu index="root" class="tree-root-menu">
                <template #title>
                  <span class="tree-root">
                    <span>⌄</span>
                    <span class="tree-label">{{ menuRoot }}</span>
                    <span></span>
                  </span>
                </template>
                <ElSubMenu
                  v-for="section in menuSections"
                  :key="section.title"
                  :index="getSectionIndex(section)"
                  class="tree-section-menu"
                >
                  <template #title>
                    <span class="tree-group">
                      <span>⌄</span>
                      <span>{{ section.title }}</span>
                      <span>{{ section.meta }}</span>
                    </span>
                  </template>
                  <ElMenuItem
                    v-for="item in section.items"
                    :key="`${section.title}-${item.index}`"
                    :index="getItemIndex(section, item)"
                    :class="['tree-node', { active: item.active }]"
                  >
                    <span>{{ item.index }}</span>
                    <span class="tree-label">{{ item.label }}</span>
                    <span v-if="item.badge" :class="['pill', item.tone || 'blue']">
                      {{ item.badge }}
                    </span>
                    <span v-else></span>
                  </ElMenuItem>
                </ElSubMenu>
              </ElSubMenu>
            </ElMenu>
          </section>

          <section class="node-files">
            <div class="node-file-head">
              <span>{{ boundaryTitle }}</span>
              <span :class="['pill', boundaryTone || 'green']">{{ boundaryBadge }}</span>
            </div>
            <table aria-hidden="true" class="table compact">
              <tbody>
                <tr v-for="row in boundaryRows" :key="row.label">
                  <th>{{ row.label }}</th>
                  <td>{{ row.value }}</td>
                </tr>
              </tbody>
            </table>
          </section>
        </aside>

        <main class="center">
          <slot></slot>
        </main>

        <aside class="right">
          <h2 class="right-title">{{ rightTitle }}</h2>
          <div v-if="rightSubtitle" class="preview-name">{{ rightSubtitle }}</div>
          <section v-for="card in rightCards" :key="card.title" class="right-card">
            <h3>{{ card.title }}</h3>
            <div class="body">
              <table v-if="card.rows?.length" aria-hidden="true" class="table compact">
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
              <div v-if="card.timeline?.length" aria-hidden="true" class="timeline">
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
  --panel: #ffffff;
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
  max-width: 100vw;
  height: 100vh;
  overflow: hidden;
  color: var(--ink);
  background: var(--bg);
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei',
    'Noto Sans CJK SC', Arial, sans-serif;
}

.aicheck-static-viewport *,
.aicheck-static-viewport *::before,
.aicheck-static-viewport *::after {
  box-sizing: border-box;
}

.app-shell {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  width: 100%;
  min-width: 0;
  max-width: 100vw;
  height: 100vh;
  min-height: 0;
  overflow-x: hidden;
  background: var(--bg);
}

.topbar {
  display: grid;
  grid-template-columns: minmax(280px, 404px) minmax(260px, 1fr) minmax(260px, 520px);
  gap: 18px;
  align-items: center;
  min-height: 68px;
  min-width: 0;
  padding: 0 20px;
  background: #fff;
  border-bottom: 1px solid var(--line);
}

.brand {
  display: grid;
  grid-template-columns: 24px 34px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  min-width: 0;
}

.hamburger {
  color: #304158;
  font-size: 22px;
  line-height: 1;
}

.brand-mark {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  color: #fff;
  font-weight: 800;
  background: linear-gradient(180deg, #4b86ff, #1761d2);
  border-radius: 8px;
}

.project-title {
  min-width: 0;
  overflow: hidden;
  color: var(--ink);
  font-size: 25px;
  font-weight: 800;
  line-height: 1.1;
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
  display: flex;
  align-items: center;
  justify-content: flex-start;
  justify-self: center;
  width: min(720px, 100%);
  height: 40px;
  padding: 0 16px;
  margin: 0;
  color: #8b98aa;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #cbd8ea;
  border-radius: 6px;
  --el-button-bg-color: #fff;
  --el-button-border-color: #cbd8ea;
  --el-button-hover-bg-color: #f8fbff;
  --el-button-hover-border-color: #9db8df;
  --el-button-hover-text-color: #52647d;
  --el-button-active-bg-color: #eef5ff;
  --el-button-active-border-color: #8fb0df;
  --el-button-active-text-color: #52647d;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.global-search :deep(span) {
  justify-content: flex-start;
  width: 100%;
}

.global-search:hover,
.global-search:focus-visible {
  color: #52647d;
  background: #f8fbff;
  border-color: #9db8df;
  outline: 0;
  box-shadow: 0 0 0 3px rgba(31, 102, 216, 0.12);
}

.top-actions {
  display: flex;
  gap: 18px;
  align-items: center;
  justify-content: flex-end;
  min-width: 0;
  color: #27364d;
  font-size: 15px;
  white-space: nowrap;
}

.notice-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  margin-left: 2px;
  color: #fff;
  font-size: 12px;
  font-weight: 800;
  background: #ef3f3b;
  border-radius: 999px;
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
  border-radius: 50%;
  background: linear-gradient(180deg, #4b83f7, #1e5ec8);
}

.user-menu {
  flex: 0 0 auto;
}

.user {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  min-height: 40px;
  padding: 0 8px 0 4px;
  color: inherit;
  font-weight: 700;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 999px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    box-shadow 0.18s ease;
}

.user:hover,
.user:focus-visible {
  color: var(--blue-2);
  background: #f4f8ff;
  outline: 0;
  box-shadow: 0 0 0 3px rgba(31, 102, 216, 0.12);
}

.user-caret {
  color: #6a7890;
  font-size: 12px;
  line-height: 1;
}

.workspace {
  display: grid;
  grid-template-columns: minmax(300px, 404px) minmax(0, 1fr) minmax(320px, 552px);
  width: 100%;
  max-width: 100vw;
  height: 100%;
  min-height: 0;
  overflow-x: hidden;
}

.left,
.center,
.right {
  min-height: 0;
}

.left {
  display: grid;
  grid-template-rows: minmax(560px, 1fr) 394px;
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  background: #fff;
  border-right: 1px solid var(--line);
}

.tree-wrap,
.node-files {
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
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
  color: #6e7d92;
  font-size: 16px;
}

.tree.static-tree-menu {
  height: calc(100% - 44px);
  padding: 8px 18px 16px;
  overflow: auto;
  background: transparent;
  border-right: 0;
  border-bottom: 1px solid var(--line);
  --el-menu-active-color: var(--blue-2);
  --el-menu-bg-color: transparent;
  --el-menu-hover-bg-color: transparent;
  --el-menu-text-color: #26364e;
}

.static-tree-menu :deep(.el-menu) {
  background: transparent;
  border-right: 0;
}

.static-tree-menu :deep(.el-sub-menu__title),
.static-tree-menu :deep(.el-menu-item) {
  height: auto;
  min-height: 34px;
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
  display: none;
}

.tree-root,
.tree-group,
.tree-node {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  min-height: 34px;
  color: #26364e;
  border-radius: 6px;
}

.tree-root,
.tree-group {
  font-weight: 800;
}

.tree-group {
  margin-top: 8px;
}

.tree-node {
  min-height: 40px;
  padding: 6px 8px;
  margin-left: 28px;
  font-weight: 600;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    box-shadow 0.18s ease;
}

.tree-node:hover,
.tree-node:focus-visible,
.tree-node.is-active {
  color: var(--blue-2);
  background: #f4f8ff;
  outline: 0;
}

.tree-node.active,
.tree-node.is-active {
  color: var(--blue-2);
  font-weight: 800;
  background: var(--blue-soft);
  box-shadow: inset 3px 0 0 var(--blue);
}

.tree-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-files {
  background: #fff;
  border-top: 1px solid var(--line);
}

.node-file-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 44px;
  padding: 0 18px;
  font-weight: 800;
}

.center {
  min-width: 0;
  height: 100%;
  padding: 18px 20px 24px;
  overflow-x: hidden;
  overflow-y: auto;
}

.right {
  min-width: 0;
  height: 100%;
  padding: 18px 20px 24px;
  overflow-x: hidden;
  overflow-y: auto;
  background: #fff;
  border-left: 1px solid var(--line);
}

.right-title {
  margin: 0 0 8px;
  font-size: 21px;
  line-height: 1.2;
}

.preview-name {
  margin-bottom: 12px;
  color: #26364e;
  font-weight: 800;
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
  box-shadow: 0 2px 8px rgba(20, 34, 56, 0.08);
}

.right-card h3 {
  margin: 0;
  padding: 13px 16px;
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
  table-layout: fixed;
  border-collapse: collapse;
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
  color: #485a73;
  font-weight: 900;
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
  grid-template-columns: 14px minmax(0, 1fr);
  gap: 9px;
  color: #3f4f66;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
}

.time-row strong {
  color: var(--ink);
  font-size: 14px;
  font-weight: 900;
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
  color: #6b2b24;
  font-weight: 800;
  line-height: 1.6;
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

@media (max-width: 1360px) {
  .topbar {
    grid-template-columns: minmax(260px, 360px) minmax(220px, 1fr);
  }

  .top-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }

  .workspace {
    grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  }

  .right {
    grid-column: 1 / -1;
    min-height: auto;
    border-top: 1px solid var(--line);
    border-left: 0;
  }
}

@media (max-width: 900px) {
  .aicheck-static-viewport {
    overflow-y: auto;
  }

  .app-shell {
    grid-template-rows: auto 1fr;
    height: auto;
    min-height: 100vh;
  }

  .topbar,
  .workspace {
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
