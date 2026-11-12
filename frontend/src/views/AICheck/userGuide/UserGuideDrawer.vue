<script setup lang="ts">
/* 使用帮助面板：账号菜单「使用帮助」打开，挂在 AICheckStaticLayout 上，所有角色共用。
 * 每件事：截图（编号圈）+ 两三步 +「带我去」。监检和管理员可以切看其他角色的说明，
 * 方便照着教施工方、无损检测、建设方；看别人的说明时不给「带我去」（那不是自己的页面）。
 * 第一次进来时弹出欢迎框（2026-11-12 用户：新手引导每个角色都要）：说清这个角色在系统里
 * 要做哪几件事，点「开始引导」在页面上一块一块讲；点过或关掉就不再出现（按账号记在本机）。
 * 原来是右下角一张小卡片，施工方很多人看不到、也不知道点。 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElDialog, ElDrawer } from 'element-plus'
import { useUserStoreWithOut } from '@/store/modules/user'
import { GUIDE_ROLES, guideForRole } from './guideContent'
import type { GuideRole, GuideTask } from './guideTypes'
import { guideOpen, jumpToGuideSpot, openUserGuide, startGuideTour } from './useUserGuide'

const route = useRoute()
const router = useRouter()
const userStore = useUserStoreWithOut()

const ownRole = computed<GuideRole | null>(() => {
  const role = String(userStore.getUserInfo?.role || '')
  return (GUIDE_ROLES as string[]).includes(role) ? (role as GuideRole) : null
})
const canSwitchRole = computed(() => ownRole.value === 'admin' || ownRole.value === 'inspection')
const viewRole = ref<GuideRole>(ownRole.value || 'contractor')
const guide = computed(() => guideForRole(viewRole.value))
const isOwnGuide = computed(() => viewRole.value === ownRole.value)

const openTaskId = ref('')
const toggleTask = (task: GuideTask) => {
  openTaskId.value = openTaskId.value === task.id ? '' : task.id
}

const isPhone = ref(false)
const updateViewport = () => {
  isPhone.value = window.innerWidth <= 640
}

// 每次打开都回到自己角色的说明，展开第一件事；面板挂载时已经是打开状态也一样
watch(
  guideOpen,
  (open) => {
    if (!open) return
    if (ownRole.value) viewRole.value = ownRole.value
    openTaskId.value = guide.value.tasks[0]?.id || ''
  },
  { immediate: true }
)
watch(viewRole, () => {
  openTaskId.value = guide.value.tasks[0]?.id || ''
})

/* 链接里带 ?help=1 时直接打开（发给别人「点这里看怎么用」） */
watch(
  () => route.query.help,
  (value) => {
    if (value && ownRole.value) openUserGuide()
  },
  { immediate: true }
)

const startTour = () => startGuideTour(router, guide.value.tour)
const jump = (task: GuideTask) => {
  if (task.jump) jumpToGuideSpot(router, task.jump)
}

/* —— 第一次进来的提示 —— */
const nudgeVisible = ref(false)
const seenKey = computed(() => {
  const user = userStore.getUserInfo
  return user ? `aicheck:guide-seen:${user.id || user.username || ''}:${user.role}` : ''
})
const readSeen = () => {
  try {
    return Boolean(seenKey.value && window.localStorage.getItem(seenKey.value))
  } catch {
    return true
  }
}
const markSeen = () => {
  nudgeVisible.value = false
  try {
    if (seenKey.value) window.localStorage.setItem(seenKey.value, new Date().toISOString())
  } catch {
    /* 存不了就算了：最多下次再提示一次 */
  }
}
let nudgeTimer = 0
watch(
  [ownRole, seenKey],
  () => {
    window.clearTimeout(nudgeTimer)
    nudgeVisible.value = false
    if (!ownRole.value || readSeen()) return
    nudgeTimer = window.setTimeout(() => {
      nudgeVisible.value = !guideOpen.value && !readSeen()
    }, 1500)
  },
  { immediate: true }
)
watch(guideOpen, (open) => {
  if (open && nudgeVisible.value) markSeen()
})
const nudgeStart = () => {
  markSeen()
  if (ownRole.value) startGuideTour(router, guideForRole(ownRole.value).tour)
}
const nudgeOpenHelp = () => {
  markSeen()
  openUserGuide()
}
/* 欢迎框里列出这个角色常办的事（不含改密码这类账号杂项），最多 5 件 */
const welcomeGuide = computed(() => (ownRole.value ? guideForRole(ownRole.value) : null))
const welcomeTasks = computed(() =>
  (welcomeGuide.value?.tasks || [])
    .filter((task) => !['account', 'switch-project', 'messages'].includes(task.id))
    .slice(0, 5)
)
const welcomeName = computed(() => {
  const user = userStore.getUserInfo
  return user?.displayName || user?.username || ''
})

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
  window.clearTimeout(nudgeTimer)
})
</script>

<template>
  <ElDrawer
    v-model="guideOpen"
    :size="isPhone ? '100%' : '560px'"
    :with-header="false"
    append-to-body
    class="user-guide-drawer"
  >
    <div class="guide">
      <header class="guide-head">
        <div>
          <h2>使用帮助</h2>
          <small>{{ guide.roleLabel }}</small>
        </div>
        <button
          type="button"
          class="guide-close"
          aria-label="关闭使用帮助"
          @click="guideOpen = false"
        >
          ×
        </button>
      </header>

      <div v-if="canSwitchRole" class="guide-roles" role="tablist" aria-label="查看哪个角色的说明">
        <button
          v-for="role in GUIDE_ROLES"
          :key="role"
          type="button"
          role="tab"
          :aria-selected="viewRole === role"
          :class="['guide-role', { 'is-active': viewRole === role }]"
          @click="viewRole = role"
        >
          {{ guideForRole(role).roleLabel }}
        </button>
      </div>

      <p class="guide-intro">{{ guide.intro }}</p>
      <button
        v-if="isOwnGuide && guide.tour.length"
        type="button"
        class="guide-tour"
        @click="startTour"
      >
        开始引导<small>在页面上一块一块讲，约 1 分钟</small>
      </button>
      <p v-else-if="!isOwnGuide" class="guide-note">
        这是{{ guide.roleLabel }}看到的说明，可以照着教对方操作。
      </p>

      <ol class="guide-tasks">
        <li v-for="(task, taskIndex) in guide.tasks" :key="task.id" class="guide-task">
          <button
            type="button"
            class="guide-task-head"
            :aria-expanded="openTaskId === task.id"
            @click="toggleTask(task)"
          >
            <span class="guide-task-no">{{ taskIndex + 1 }}</span>
            <span class="guide-task-text">
              <strong>{{ task.title }}</strong>
              <small>{{ task.summary }}</small>
            </span>
            <span class="guide-chevron" aria-hidden="true">{{
              openTaskId === task.id ? '−' : '+'
            }}</span>
          </button>
          <div v-if="openTaskId === task.id" class="guide-task-body">
            <figure v-if="task.image" :class="['guide-shot', `is-${task.image.device}`]">
              <div class="guide-shot-frame">
                <img :src="task.image.src" :alt="task.image.alt" loading="lazy" />
                <span
                  v-for="marker in task.image.markers || []"
                  :key="marker.n"
                  class="guide-marker"
                  :style="{ left: `${marker.x}%`, top: `${marker.y}%` }"
                  aria-hidden="true"
                  >{{ marker.n }}</span
                >
              </div>
            </figure>
            <ol class="guide-steps">
              <li v-for="(step, stepIndex) in task.steps" :key="stepIndex">
                <span class="guide-step-no">{{ stepIndex + 1 }}</span>
                <span>{{ step }}</span>
              </li>
            </ol>
            <button
              v-if="task.jump && isOwnGuide"
              type="button"
              class="guide-jump"
              @click="jump(task)"
            >
              {{ task.jump.label || '去看看' }} →
            </button>
          </div>
        </li>
      </ol>

      <section v-if="guide.faq.length" class="guide-faq" aria-label="常见问题">
        <h3>常见问题</h3>
        <details v-for="item in guide.faq" :key="item.q">
          <summary>{{ item.q }}</summary>
          <p>{{ item.a }}</p>
        </details>
      </section>
    </div>
  </ElDrawer>

  <!-- 第一次进来：欢迎框。关掉也算看过，帮助随时在账号菜单里 -->
  <ElDialog
    :model-value="nudgeVisible && Boolean(welcomeGuide)"
    :width="isPhone ? '92%' : '460px'"
    :close-on-click-modal="false"
    append-to-body
    align-center
    class="guide-welcome"
    :show-close="true"
    @close="markSeen"
  >
    <template #header>
      <div class="guide-welcome-head">
        <strong>欢迎{{ welcomeName ? `，${welcomeName}` : '' }}</strong>
        <small>你的身份：{{ welcomeGuide?.roleLabel }}</small>
      </div>
    </template>
    <p class="guide-welcome-intro">{{ welcomeGuide?.intro }}</p>
    <p class="guide-welcome-label">你在这里常做的事：</p>
    <ol class="guide-welcome-tasks" data-testid="guide-welcome-tasks">
      <li v-for="task in welcomeTasks" :key="task.id">
        <strong>{{ task.title }}</strong>
        <small>{{ task.summary }}</small>
      </li>
    </ol>
    <p class="guide-welcome-note">
      不会用了随时点右上角你的名字 →「使用帮助」，可以重看这份说明和引导。
    </p>
    <template #footer>
      <div class="guide-nudge-actions">
        <button type="button" class="is-quiet" @click="markSeen">先自己看看</button>
        <button type="button" class="is-quiet" @click="nudgeOpenHelp">看图文说明</button>
        <button type="button" class="is-primary" @click="nudgeStart">
          开始引导（约 1 分钟）
        </button>
      </div>
    </template>
  </ElDialog>
</template>

<style scoped>
@media (width <= 640px) {
  .guide {
    padding: 14px 16px 24px;
  }

  .guide-nudge-actions .is-primary {
    flex: 1 1 100%;
  }
}

.guide {
  display: grid;
  padding: 18px 20px 28px;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
}

.guide-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
}

.guide-head h2 {
  margin: 0;
  font-size: 20px;
  line-height: 28px;
  color: #172033;
}

.guide-head small {
  font-size: 13px;
  color: #667085;
}

.guide-close {
  display: grid;
  width: 40px;
  height: 40px;
  padding: 0;
  font-size: 24px;
  line-height: 1;
  color: #667085;
  cursor: pointer;
  background: none;
  border: 0;
  border-radius: 8px;
  place-items: center;
}

.guide-close:hover {
  background: #f2f4f7;
}

.guide-roles {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.guide-role {
  min-height: 34px;
  padding: 0 12px;
  font: inherit;
  font-size: 13px;
  color: #475467;
  cursor: pointer;
  background: #f2f4f7;
  border: 1px solid transparent;
  border-radius: 999px;
}

.guide-role.is-active {
  color: #1d3f8f;
  background: #eef4ff;
  border-color: #c9d8f6;
}

.guide-intro,
.guide-note {
  margin: 0;
  font-size: 14px;
  line-height: 22px;
  color: #475467;
}

.guide-note {
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 8px;
}

.guide-tour {
  display: grid;
  min-height: 56px;
  padding: 10px 14px;
  font: inherit;
  font-size: 16px;
  font-weight: 600;
  color: #fff;
  text-align: left;
  cursor: pointer;
  background: #2f6bff;
  border: 0;
  border-radius: 12px;
  gap: 2px;
}

.guide-tour small {
  font-size: 12px;
  font-weight: 400;
  color: rgb(255 255 255 / 85%);
}

.guide-tasks {
  display: grid;
  padding: 0;
  margin: 0;
  overflow: hidden;
  list-style: none;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 12px;
}

.guide-task + .guide-task {
  border-top: 1px solid #eef1f6;
}

.guide-task-head {
  display: flex;
  width: 100%;
  min-height: 60px;
  padding: 10px 14px;
  font: inherit;
  color: inherit;
  text-align: left;
  cursor: pointer;
  background: none;
  border: 0;
  gap: 12px;
  align-items: center;
}

.guide-task-head:hover {
  background: #f8fafc;
}

.guide-task-no,
.guide-step-no {
  display: inline-grid;
  width: 24px;
  height: 24px;
  font-size: 13px;
  font-weight: 600;
  color: #1d3f8f;
  background: #eef4ff;
  border-radius: 999px;
  flex: none;
  place-items: center;
}

.guide-task-text {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 2px;
}

.guide-task-text strong {
  font-size: 15px;
  color: #172033;
}

.guide-task-text small {
  font-size: 13px;
  line-height: 18px;
  color: #667085;
}

.guide-chevron {
  width: 20px;
  font-size: 20px;
  color: #98a2b3;
  text-align: center;
}

.guide-task-body {
  display: grid;
  padding: 4px 14px 16px;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
}

.guide-shot {
  margin: 0;
}

.guide-shot-frame {
  position: relative;
  overflow: hidden;
  background: #f8fafc;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
}

.guide-shot.is-phone .guide-shot-frame {
  max-width: 300px;
  margin: 0 auto;
}

.guide-shot img {
  display: block;
  width: 100%;
  height: auto;
}

/* 编号圈：和下面步骤前的数字一样 */
.guide-marker {
  position: absolute;
  display: grid;
  width: 24px;
  height: 24px;
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  background: #e5484d;
  border: 2px solid #fff;
  border-radius: 999px;
  transform: translate(-50%, -50%);
  box-shadow: 0 2px 6px rgb(15 23 42 / 30%);
  place-items: center;
}

.guide-steps {
  display: grid;
  padding: 0;
  margin: 0;
  list-style: none;
  gap: 8px;
}

.guide-steps li {
  display: flex;
  font-size: 14px;
  line-height: 22px;
  color: #344054;
  gap: 10px;
}

.guide-steps .guide-step-no {
  color: #fff;
  background: #e5484d;
}

.guide-jump {
  justify-self: start;
  min-height: 40px;
  padding: 0 16px;
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  color: #1d3f8f;
  cursor: pointer;
  background: #f3f7ff;
  border: 1px solid #d6e2fb;
  border-radius: 8px;
}

.guide-faq {
  display: grid;
  gap: 8px;
}

.guide-faq h3 {
  margin: 6px 0 0;
  font-size: 15px;
  color: #172033;
}

.guide-faq details {
  padding: 10px 14px;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
}

.guide-faq summary {
  font-size: 14px;
  color: #172033;
  cursor: pointer;
}

.guide-faq p {
  margin: 8px 0 0;
  font-size: 14px;
  line-height: 22px;
  color: #475467;
}

.guide-welcome-head {
  display: grid;
  gap: 2px;
}

.guide-welcome-head strong {
  font-size: 18px;
  color: #172033;
}

.guide-welcome-head small,
.guide-welcome-tasks small {
  font-size: 13px;
  color: #667085;
}

.guide-welcome-intro {
  margin: 0 0 12px;
  font-size: 15px;
  line-height: 24px;
  color: #344054;
}

.guide-welcome-label {
  margin: 0 0 6px;
  font-weight: 600;
  color: #172033;
}

.guide-welcome-tasks {
  display: grid;
  padding-left: 22px;
  margin: 0 0 12px;
  gap: 8px;
}

.guide-welcome-tasks li {
  display: grid;
  line-height: 21px;
}

.guide-welcome-note {
  padding: 8px 10px;
  margin: 0;
  font-size: 13px;
  line-height: 20px;
  color: #475467;
  background: #f5f7fb;
  border-radius: 8px;
}

.guide-nudge-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.guide-nudge-actions button {
  min-height: 44px;
  padding: 0 14px;
  font: inherit;
  font-size: 14px;
  cursor: pointer;
  border-radius: 8px;
}

.guide-nudge-actions .is-quiet {
  color: #667085;
  background: none;
  border: 0;
}

.guide-nudge-actions .is-primary {
  color: #fff;
  background: #2f6bff;
  border: 1px solid #2f6bff;
}
</style>
