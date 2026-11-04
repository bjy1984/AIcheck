<script setup lang="ts">
/* 意见反馈入口：挂在 AICheckStaticLayout 上，所有工作台和后台页面都有。
 * 贴在屏幕右侧中部——右下角是监检页的 AI 助手。
 * 自动带上当前页面和地址栏里的工程/节点，管理员不用再问「你是在哪一页遇到的」。 */
import { computed, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  ElButton,
  ElDialog,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElRadioButton,
  ElRadioGroup,
  ElTabPane,
  ElTabs,
  ElTag
} from 'element-plus'
import { confirmUserFeedbackApi, getMyUserFeedbackApi, submitUserFeedbackApi } from '@/api/aicheck'
import {
  USER_FEEDBACK_CATEGORIES,
  type UserFeedback,
  type UserFeedbackCategory
} from '@/api/aicheck/userFeedback'
import { useUserStoreWithOut } from '@/store/modules/user'
import { getAicheckErrorMessage } from '@/utils/aicheckError'

const route = useRoute()
const userStore = useUserStoreWithOut()

// FDE 是内部治理角色，没有提交权限；没登录也不显示
const visible = computed(() => {
  const role = userStore.getUserInfo?.role
  return Boolean(role) && role !== 'fde'
})

const open = ref(false)
const activeTab = ref<'submit' | 'mine'>('submit')
const form = reactive<{ category: UserFeedbackCategory; content: string }>({
  category: 'usability',
  content: ''
})
const submitting = ref(false)
const submitError = ref('')
const mine = ref<UserFeedback[]>([])
const mineLoading = ref(false)
const mineError = ref('')
// 每次打开表单换一个幂等键：连点两下提交不会多出一条
let idempotencyKey = ''

const categoryHint = computed(
  () => USER_FEEDBACK_CATEGORIES.find((item) => item.value === form.category)?.hint || ''
)
const queryText = (value: unknown) => {
  const first = Array.isArray(value) ? value[0] : value
  return first ? String(first) : ''
}
const context = computed(() => ({
  page: route.fullPath,
  pageTitle: String(route.meta?.title || document.title || ''),
  projectId: queryText(route.query.projectId) || undefined,
  nodeId: queryText(route.query.nodeId) || undefined
}))
const contextLabel = computed(() => {
  const parts = [context.value.pageTitle || context.value.page]
  if (context.value.projectId) parts.push(`工程 ${context.value.projectId}`)
  if (context.value.nodeId) parts.push(`节点 ${context.value.nodeId}`)
  return parts.join(' · ')
})
/* 平台标为已上线后，提交人确认（2026-11-04）：已解决就关闭；仍有问题写原因，任务重新打开 */
const awaitingConfirm = (item: UserFeedback) =>
  item.status === 'escalated' && item.platformTask?.status === 'deployed'
const confirming = ref('')
const confirmFix = async (item: UserFeedback, resolved: boolean) => {
  let note = ''
  if (!resolved) {
    try {
      const { value } = await ElMessageBox.prompt(
        '写一句哪里还不对，平台会照着重修。',
        '仍有问题',
        {
          confirmButtonText: '提交',
          cancelButtonText: '取消',
          inputType: 'textarea',
          inputValidator: (input: string) => Boolean(String(input || '').trim()) || '请填写'
        }
      )
      note = String(value || '').trim()
    } catch {
      return
    }
  }
  confirming.value = item.id
  try {
    await confirmUserFeedbackApi(
      item.id,
      { resolved, note: note || undefined },
      { idempotencyKey: `user-feedback-confirm-${item.id}-${Date.now()}` }
    )
    ElMessage.success(resolved ? '已确认解决，谢谢反馈。' : '已退回平台重修。')
    await loadMine()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '提交失败，请稍后重试。'))
  } finally {
    confirming.value = ''
  }
}

const repliedCount = computed(() => mine.value.filter((item) => item.reply).length)

const loadMine = async () => {
  mineLoading.value = true
  mineError.value = ''
  try {
    const res = await getMyUserFeedbackApi()
    mine.value = res.data?.items || []
  } catch (error) {
    mineError.value = getAicheckErrorMessage(error, '我的反馈加载失败，请稍后重试。')
  } finally {
    mineLoading.value = false
  }
}

const openDialog = () => {
  idempotencyKey = `user-feedback-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  submitError.value = ''
  open.value = true
  void loadMine()
}

const submit = async () => {
  const content = form.content.trim()
  if (content.length < 5) {
    submitError.value = '请把问题写清楚一些（至少 5 个字）。'
    return
  }
  submitting.value = true
  submitError.value = ''
  try {
    await submitUserFeedbackApi(
      { category: form.category, content, context: context.value },
      { idempotencyKey }
    )
    ElMessage.success('已提交给管理员，处理后可在「我的反馈」里看到回复。')
    form.content = ''
    idempotencyKey = `user-feedback-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    activeTab.value = 'mine'
    await loadMine()
  } catch (error) {
    submitError.value = getAicheckErrorMessage(error, '提交失败，请稍后重试。')
  } finally {
    submitting.value = false
  }
}

const statusTagType = (status: string) =>
  (
    ({
      open: 'info',
      acknowledged: 'warning',
      resolved: 'success',
      declined: 'danger',
      escalated: 'primary'
    }) as const
  )[status as 'open']
</script>

<template>
  <template v-if="visible">
    <button type="button" class="feedback-tab" aria-label="意见反馈" @click="openDialog"
      >意见反馈</button
    >
    <ElDialog v-model="open" title="意见反馈" width="min(560px, calc(100vw - 32px))" append-to-body>
      <ElTabs v-model="activeTab">
        <ElTabPane label="提交反馈" name="submit">
          <p class="lead">使用中遇到不方便、审计结论不准确或功能异常，都可以直接告诉管理员。</p>
          <div class="field">
            <span class="field-label">反馈类型</span>
            <ElRadioGroup v-model="form.category" size="small">
              <ElRadioButton
                v-for="item in USER_FEEDBACK_CATEGORIES"
                :key="item.value"
                :value="item.value"
                >{{ item.label }}</ElRadioButton
              >
            </ElRadioGroup>
            <small v-if="categoryHint" class="hint">{{ categoryHint }}</small>
          </div>
          <div class="field">
            <span class="field-label">具体情况</span>
            <ElInput
              v-model="form.content"
              type="textarea"
              :rows="5"
              maxlength="2000"
              show-word-limit
              aria-label="具体情况"
              :placeholder="
                form.category === 'audit_accuracy'
                  ? '哪个节点、哪一项判断不对，资料里实际写的是什么'
                  : '在做什么操作时遇到的，希望怎样改'
              "
            />
          </div>
          <p class="context">会一并附上：{{ contextLabel }}</p>
          <p v-if="submitError" class="error" role="alert">{{ submitError }}</p>
          <div class="actions">
            <ElButton @click="open = false">取消</ElButton>
            <ElButton type="primary" :loading="submitting" @click="submit">提交</ElButton>
          </div>
        </ElTabPane>
        <ElTabPane
          :label="repliedCount ? `我的反馈（${repliedCount} 条已回复）` : '我的反馈'"
          name="mine"
        >
          <p v-if="mineError" class="error" role="alert">{{ mineError }}</p>
          <p v-else-if="mineLoading" class="muted">加载中…</p>
          <p v-else-if="!mine.length" class="muted">还没有提交过反馈。</p>
          <ul v-else class="mine-list">
            <li v-for="item in mine" :key="item.id">
              <div class="mine-head">
                <ElTag size="small" :type="statusTagType(item.status)">{{
                  item.statusLabel
                }}</ElTag>
                <span>{{ item.categoryLabel }}</span>
                <time>{{ item.createdAt }}</time>
              </div>
              <p class="mine-content">{{ item.content }}</p>
              <!-- 送平台审批后的进度（2026-11-04）：平台审批、AI 修复、上线，都会更新这里 -->
              <p v-if="item.platformTask" class="mine-platform">
                平台进度：{{ item.platformTask.statusLabel }}
              </p>
              <div v-if="awaitingConfirm(item)" class="mine-confirm">
                <span>平台说已修好上线，请确认：</span>
                <ElButton
                  size="small"
                  type="primary"
                  :loading="confirming === item.id"
                  @click="confirmFix(item, true)"
                  >已解决</ElButton
                >
                <ElButton
                  size="small"
                  :disabled="confirming === item.id"
                  @click="confirmFix(item, false)"
                  >仍有问题</ElButton
                >
              </div>
              <p v-if="item.reply" class="mine-reply">
                <strong>{{ item.reply.repliedBy }} 回复：</strong>{{ item.reply.content }}
              </p>
            </li>
          </ul>
        </ElTabPane>
      </ElTabs>
    </ElDialog>
  </template>
</template>

<style scoped>
.feedback-tab {
  position: fixed;
  top: 50%;
  right: 0;
  z-index: 1800;
  padding: 12px 6px;
  font-size: 13px;
  line-height: 1.2;
  color: #fff;
  letter-spacing: 2px;
  cursor: pointer;
  background: var(--el-color-primary);
  border: 0;
  border-radius: 6px 0 0 6px;
  box-shadow: 0 2px 8px rgb(0 0 0 / 15%);
  transform: translateY(-50%);
  writing-mode: vertical-rl;
}

.feedback-tab:hover,
.feedback-tab:focus-visible {
  background: var(--el-color-primary-dark-2);
  outline: none;
}

.lead,
.context,
.muted {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.field {
  display: grid;
  gap: 6px;
  margin-bottom: 14px;
}

/* 窄屏时类型 / 状态按钮换行，不被挤出弹窗 */
.field :deep(.el-radio-group) {
  flex-wrap: wrap;
  row-gap: 6px;
}

.field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.hint {
  color: var(--el-text-color-secondary);
}

.error {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--el-color-danger);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.mine-list {
  max-height: 420px;
  padding: 0;
  margin: 0;
  overflow-y: auto;
  list-style: none;
}

.mine-list li {
  padding: 10px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.mine-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.mine-head time {
  margin-left: auto;
  color: var(--el-text-color-secondary);
}

.mine-content,
.mine-reply {
  margin: 6px 0 0;
  font-size: 13px;
  white-space: pre-wrap;
}

.mine-confirm {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 8px;
  font-size: 13px;
}

.mine-platform {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-color-primary);
}

.mine-reply {
  padding: 8px 10px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
}
</style>
