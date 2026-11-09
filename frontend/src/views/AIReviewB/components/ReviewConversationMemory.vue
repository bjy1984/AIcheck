<script setup lang="ts">
/**
 * 对话记忆的工具条：开始新对话、AI 回答偏好。放在对话栏标题行，对话再长也够得着。
 *
 * 上一段对话的要点和闲置提示在 ReviewConversationCarryOver（对话开头）。
 * 规则见 backend/apps/api/review_session_memory.py。
 */
import { computed, ref } from 'vue'
import { ElButton, ElDialog, ElInput, ElMessage, ElMessageBox } from 'element-plus'
import {
  getReviewAssistantPreferencesApi,
  restartReviewBSessionApi,
  saveReviewAssistantPreferencesApi
} from '@/api/aiReviewB'
import type { ReviewBSession } from '@/types/ai-review-b'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import { preferenceLength } from '../conversationMemory'

const props = defineProps<{
  session?: ReviewBSession | null
  /** 有回答在执行、或正在发起复核：这时不能换会话 */
  busy?: boolean
  /** 新对话的「当前问题」：节点的检验项目，而不是上一段对话最后那句话 */
  currentTask?: string
}>()
const emit = defineEmits<{ restarted: [session: ReviewBSession] }>()

const restarting = ref(false)
const historyDays = computed(() => props.session?.memory?.historyDays || 7)

const startNewConversation = async () => {
  const session = props.session
  if (!session || props.busy) return
  try {
    await ElMessageBox.confirm(
      '当前这段对话会结束并留档，之后还能翻看；新对话里 AI 只带上其中几条要点，结论会按当前资料重新核实。',
      '开始新对话',
      { type: 'info', confirmButtonText: '开始新对话', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  restarting.value = true
  try {
    const res = await restartReviewBSessionApi(
      session.id,
      { currentTask: props.currentTask || undefined },
      { etag: session.etag }
    )
    emit('restarted', res.data.session)
    ElMessage.success('已开始新对话')
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '新对话没有开成，请刷新后再试。'))
  } finally {
    restarting.value = false
  }
}

const preferencesOpen = ref(false)
const preferencesLoading = ref(false)
const preferencesSaving = ref(false)
const preferenceDraft = ref('')
const preferenceMax = ref(300)
const preferenceSaved = ref('')
const preferenceTooLong = computed(
  () => preferenceLength(preferenceDraft.value) > preferenceMax.value
)

const openPreferences = async () => {
  preferencesOpen.value = true
  preferencesLoading.value = true
  try {
    const res = await getReviewAssistantPreferencesApi()
    preferenceMax.value = res.data.preferences.maxLength || 300
    preferenceSaved.value = res.data.preferences.text || ''
    preferenceDraft.value = preferenceSaved.value
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '回答偏好没有读出来。'))
  } finally {
    preferencesLoading.value = false
  }
}

const savePreferences = async (text: string) => {
  preferencesSaving.value = true
  try {
    const res = await saveReviewAssistantPreferencesApi(text)
    preferenceSaved.value = res.data.preferences.text || ''
    preferenceDraft.value = preferenceSaved.value
    preferencesOpen.value = false
    ElMessage.success(preferenceSaved.value ? '回答偏好已保存，下一次提问起生效' : '回答偏好已清空')
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '回答偏好没有保存成功。'))
  } finally {
    preferencesSaving.value = false
  }
}
</script>

<template>
  <div v-if="session" class="conversation-memory-toolbar" aria-label="对话记忆">
    <span class="memory-scope" :title="`AI 只参考这段对话最近 ${historyDays} 天的内容`"
      >参考近 {{ historyDays }} 天对话</span
    >
    <ElButton size="small" text @click="openPreferences">回答偏好</ElButton>
    <ElButton
      size="small"
      :loading="restarting"
      :disabled="busy || restarting"
      :title="busy ? '有回答在执行，等它完成再开始新对话' : '结束这段对话，开一段新的'"
      @click="startNewConversation"
      >新对话</ElButton
    >

    <ElDialog
      v-model="preferencesOpen"
      title="AI 回答偏好"
      width="min(460px, calc(100vw - 32px))"
      append-to-body
    >
      <div v-loading="preferencesLoading">
        <p class="preference-note">
          写下你希望 AI
          怎么回答，例如「先列不符合项」「回答短一点」。只影响表达方式，不影响判定依据和结论；只对你自己的对话生效，每次提问都会带上。
        </p>
        <ElInput
          v-model="preferenceDraft"
          type="textarea"
          :rows="4"
          :maxlength="preferenceMax"
          show-word-limit
          placeholder="例如：先给结论表，再列需要施工方补交的资料"
          aria-label="AI 回答偏好"
        />
      </div>
      <template #footer>
        <ElButton :disabled="preferencesSaving || !preferenceSaved" @click="savePreferences('')"
          >清空</ElButton
        >
        <ElButton @click="preferencesOpen = false">取消</ElButton>
        <ElButton
          type="primary"
          :loading="preferencesSaving"
          :disabled="preferencesLoading || preferenceTooLong"
          @click="savePreferences(preferenceDraft)"
          >保存</ElButton
        >
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.conversation-memory-toolbar {
  display: inline-flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  justify-content: flex-end;
}

.memory-scope {
  margin-right: 4px;
  font-size: 12px;
  color: var(--review-muted, #667085);
  white-space: nowrap;
}

.preference-note {
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--review-muted, #667085);
}
</style>
