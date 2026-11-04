<script setup lang="ts">
/* 院级审查口径开关（2026-11-04，意见反馈审批方案第二阶段）。
 * 各院对少数「怎么判」的口径做法不同：平台给默认值，各院可以改；选项里没有「符合」——只能更严或同等。
 * 平台管理员多看到各院怎么选的分布，多数院选同一种时把它升级成平台默认。 */
import { computed, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElMessage,
  ElOption,
  ElRadio,
  ElRadioGroup,
  ElSelect,
  ElTag
} from 'element-plus'
import StaticPageShell from './components/StaticPageShell.vue'
import {
  getReviewPoliciesApi,
  setInstituteReviewPolicyApi,
  setPlatformReviewPolicyDefaultApi
} from '@/api/aicheck'
import type { ReviewPolicy, ReviewPolicySource } from '@/api/aicheck/reviewPolicies'
import { useUserStoreWithOut } from '@/store/modules/user'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import {
  ADMIN_BOUNDARY_BADGE,
  ADMIN_BOUNDARY_TITLE,
  ADMIN_MENU_ROOT,
  ADMIN_MENU_TITLE,
  buildAdminMenuSections
} from './adminMenuTree'

const FOLLOW = '__follow__'
const SOURCE_LABELS: Record<ReviewPolicySource, string> = {
  institute: '本院设定',
  platform: '平台默认',
  code: '系统默认'
}

const userStore = useUserStoreWithOut()
const platformAdmin = computed(() => Boolean(userStore.getUserInfo?.platformAdmin))
const userLabel = computed(
  () => userStore.getUserInfo?.displayName || userStore.getUserInfo?.username || '系统管理员'
)
const menuSections = computed(() =>
  buildAdminMenuSections('/admin/review-policies', { platformAdmin: platformAdmin.value })
)

const items = ref<ReviewPolicy[]>([])
const loading = ref(false)
const loadError = ref('')
const saving = ref('')
const choices = ref<Record<string, string>>({})
const platformChoices = ref<Record<string, string>>({})

const load = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const res = await getReviewPoliciesApi()
    items.value = res.data?.items || []
    choices.value = Object.fromEntries(
      items.value.map((item) => [item.key, item.instituteValue || FOLLOW])
    )
    platformChoices.value = Object.fromEntries(
      items.value.map((item) => [item.key, item.platformDefault || FOLLOW])
    )
  } catch (error) {
    loadError.value = getAicheckErrorMessage(error, '审查口径加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

const optionLabel = (item: ReviewPolicy, value: string | null) =>
  item.options.find((option) => option.value === value)?.label || value || ''

const followLabel = (item: ReviewPolicy) =>
  `跟随平台默认（${optionLabel(item, item.platformDefault || item.codeDefault)}）`

const saveInstitute = async (item: ReviewPolicy) => {
  const value = choices.value[item.key] === FOLLOW ? null : choices.value[item.key]
  saving.value = item.key
  try {
    await setInstituteReviewPolicyApi(item.key, value, {
      idempotencyKey: `review-policy-${item.key}-${Date.now()}`
    })
    ElMessage.success('已保存：之后的审查按这个口径判，已有结论不会自动改。')
    await load()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '保存失败，请稍后重试。'))
  } finally {
    saving.value = ''
  }
}

const savePlatform = async (item: ReviewPolicy) => {
  const value = platformChoices.value[item.key] === FOLLOW ? null : platformChoices.value[item.key]
  saving.value = `platform-${item.key}`
  try {
    await setPlatformReviewPolicyDefaultApi(item.key, value, {
      idempotencyKey: `review-policy-default-${item.key}-${Date.now()}`
    })
    ElMessage.success('平台默认已更新：没有自己设定的院都按它判。')
    await load()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '保存失败，请稍后重试。'))
  } finally {
    saving.value = ''
  }
}

const rightCards = computed(() => [
  {
    title: '口径说明',
    rows: [
      { label: '本院设定', value: '只影响本院之后的审查' },
      { label: '平台默认', value: '本院没设定时用它' },
      { label: '选项', value: '没有「符合」：只能更严或同等' }
    ],
    note: '改口径不会重算已有结论；要按新口径判，对相关节点重新发起复核。'
  }
])

onMounted(load)
</script>

<template>
  <StaticPageShell
    brand-mark="RP"
    title="审查口径"
    :status="loadError ? '加载异常' : `${items.length} 个开关`"
    :status-tone="loadError ? 'red' : 'green'"
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
    right-toggle-label="口径说明"
    right-collapsed-default
    boundary-collapsed-default
    search-scope="admin"
    task-area="admin"
  >
    <section class="policies-page" aria-labelledby="policies-heading">
      <div class="heading-row">
        <div>
          <h2 id="policies-heading">审查口径</h2>
          <p>
            各院做法可能不同的几处判法。本院没设定就跟随平台默认；选项里没有「符合」，只能更严或同等。
          </p>
        </div>
        <ElButton :loading="loading" @click="load">刷新</ElButton>
      </div>
      <ElAlert v-if="loadError" type="error" :closable="false" :title="loadError" />
      <ElCard v-for="item in items" :key="item.key" shadow="never" class="policy-card">
        <div class="policy-head">
          <h3>{{ item.label }}</h3>
          <ElTag size="small" :type="item.effective.source === 'institute' ? 'warning' : 'info'"
            >现在按：{{ optionLabel(item, item.effective.value) }} ·
            {{ SOURCE_LABELS[item.effective.source] }}</ElTag
          >
        </div>
        <p class="policy-desc">{{ item.description }}</p>
        <p class="muted">适用：{{ item.appliesTo }}</p>

        <div class="field">
          <span class="field-label">本院口径</span>
          <ElRadioGroup v-model="choices[item.key]" class="choice-group">
            <ElRadio :value="FOLLOW">{{ followLabel(item) }}</ElRadio>
            <ElRadio v-for="option in item.options" :key="option.value" :value="option.value">{{
              option.label
            }}</ElRadio>
          </ElRadioGroup>
          <div>
            <ElButton
              size="small"
              type="primary"
              :loading="saving === item.key"
              :disabled="choices[item.key] === (item.instituteValue || FOLLOW)"
              @click="saveInstitute(item)"
              >保存本院口径</ElButton
            >
          </div>
        </div>

        <div v-if="platformAdmin && item.adoption" class="platform-block">
          <span class="field-label">各院怎么选（平台管理员可见）</span>
          <ul class="adoption">
            <li v-for="option in item.options" :key="option.value">
              <strong>{{ option.label }}</strong
              >：
              <span v-if="item.adoption[option.value]?.length">{{
                item.adoption[option.value].map((who) => who.name).join('、')
              }}</span>
              <span v-else class="muted">无</span>
            </li>
          </ul>
          <div class="platform-default">
            <span class="field-label">平台默认</span>
            <ElSelect v-model="platformChoices[item.key]" size="small" class="default-select">
              <ElOption
                :value="FOLLOW"
                :label="`系统默认（${optionLabel(item, item.codeDefault)}）`"
              />
              <ElOption
                v-for="option in item.options"
                :key="option.value"
                :value="option.value"
                :label="option.label"
              />
            </ElSelect>
            <ElButton
              size="small"
              :loading="saving === `platform-${item.key}`"
              :disabled="platformChoices[item.key] === (item.platformDefault || FOLLOW)"
              @click="savePlatform(item)"
              >保存平台默认</ElButton
            >
          </div>
        </div>
      </ElCard>
    </section>
  </StaticPageShell>
</template>

<style scoped>
.policies-page {
  display: grid;
  gap: 16px;
}

.heading-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.heading-row h2 {
  margin: 0 0 4px;
  font-size: 18px;
}

.heading-row p,
.muted {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.policy-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  justify-content: space-between;
}

.policy-head h3 {
  margin: 0;
  font-size: 15px;
}

.policy-desc {
  margin: 8px 0 4px;
  font-size: 13px;
  line-height: 1.6;
}

.field {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}

.field-label {
  font-size: 13px;
  font-weight: 600;
}

.choice-group {
  display: grid;
  gap: 6px;
  justify-items: start;
}

.platform-block {
  display: grid;
  gap: 8px;
  padding-top: 12px;
  margin-top: 14px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.adoption {
  display: grid;
  gap: 4px;
  padding-left: 18px;
  margin: 0;
  font-size: 13px;
}

.platform-default {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.default-select {
  width: min(280px, 100%);
}
</style>
