<script setup lang="ts">
/**
 * 对话开头的两样东西：会话闲置超期的提示，以及上一段对话带过来的要点（可拿掉）。
 *
 * 这些要点会进 AI 的上下文，所以要摆在用户眼前：用户能看见 AI 被告知了什么，也能拿掉它。
 * 规则见 backend/apps/api/review_session_memory.py。
 */
import { computed, ref } from 'vue'
import { ElButton, ElMessage } from 'element-plus'
import { dismissReviewBCarryOverApi } from '@/api/aiReviewB'
import type { ReviewBSession } from '@/types/ai-review-b'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import { carryOverDigest, carryOverLines, historyHint, shortStamp } from '../conversationMemory'

const props = defineProps<{
  session?: ReviewBSession | null
  /** 对话里已经有消息时要点默认收起，只留一行标题 */
  hasMessages?: boolean
}>()
const emit = defineEmits<{ updated: [session: ReviewBSession] }>()

const dismissing = ref(false)
const lines = computed(() => carryOverLines(props.session?.carryOver))
const digest = computed(() => carryOverDigest(lines.value))
const hint = computed(() => historyHint(props.session))
const lastActivity = computed(() => shortStamp(props.session?.carryOver?.lastActivityAt))

const dismiss = async () => {
  const session = props.session
  if (!session) return
  dismissing.value = true
  try {
    const res = await dismissReviewBCarryOverApi(session.id, { etag: session.etag })
    emit('updated', res.data.session)
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '操作没有成功，请刷新后再试。'))
  } finally {
    dismissing.value = false
  }
}
</script>

<template>
  <div v-if="hint || lines.length" class="conversation-carry-over">
    <p v-if="hint" class="memory-hint" role="status">{{ hint }}</p>

    <details v-if="lines.length" class="carry-over" :open="!hasMessages">
      <summary>
        <strong>上次对话要点</strong>
        <!-- 收起时也看得出 AI 被告知了什么：结论摘要放在标题行里，展开才看原话 -->
        <span class="carry-over-digest">
          <span
            v-for="chip in digest"
            :key="chip.verdict"
            :class="['carry-over-verdict', `is-${chip.tone}`]"
            >{{ chip.verdict }}<template v-if="chip.count > 1"> ×{{ chip.count }}</template></span
          >
        </span>
        <span v-if="lastActivity" class="carry-over-time">{{ lastActivity }}</span>
      </summary>
      <p class="carry-over-note">AI 只把这几条当线索，结论会按当前资料重新核实。</p>
      <ul>
        <li v-for="line in lines" :key="line.key">
          <span :class="['carry-over-verdict', `is-${line.tone}`]">{{ line.verdict }}</span>
          <span class="carry-over-text"
            >{{ line.question
            }}<span v-if="line.summary" class="carry-over-summary">（{{ line.summary }}）</span
            ><template v-if="line.answer">：{{ line.answer }}</template></span
          >
        </li>
      </ul>
      <ElButton link size="small" :loading="dismissing" @click="dismiss">不再带上</ElButton>
    </details>
  </div>
</template>

<style scoped>
.conversation-carry-over {
  display: grid;
  gap: 8px;
  margin-bottom: 14px;
}

.memory-hint {
  padding: 8px 12px;
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #8a5300;
  background: #fff8ec;
  border: 1px solid #ffe0ad;
  border-radius: 8px;
}

.carry-over {
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid var(--review-line, #e3e9f3);
  border-radius: 8px;
}

.carry-over summary {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  align-items: center;
  font-size: 13px;
  color: var(--review-ink, #172033);
  cursor: pointer;
}

.carry-over-digest {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}

.carry-over-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--review-muted, #667085);
}

/* 展开后封顶、内部滚动：悬浮助手里输入框（约 160px）钉在底部，可视区随屏幕高度缩小，
   一张不封顶的卡片会被输入框压住最后几条（2026-11-09 生产验收）。
   430px ≈ 面板顶部偏移 + 标题与工具行 + 输入框，按 560 高实测：卡片底边停在输入框上方。 */
.carry-over[open] {
  max-height: clamp(88px, calc(100vh - 430px), 240px);
  overflow-y: auto;
  overscroll-behavior: contain;
}

.carry-over-note {
  margin: 6px 0;
  font-size: 12px;
  color: var(--review-muted, #667085);
}

.carry-over ul {
  display: grid;
  gap: 6px;
  padding: 0;
  margin: 0 0 4px;
  list-style: none;
}

.carry-over li {
  display: flex;
  gap: 8px;
  align-items: baseline;
  min-width: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #344054;
}

.carry-over-text {
  min-width: 0;
  overflow-wrap: anywhere;
}

.carry-over-summary {
  color: var(--review-muted, #667085);
}

.carry-over-verdict {
  flex: 0 0 auto;
  padding: 0 6px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 4px;
}

.carry-over-verdict.is-danger {
  color: #b42318;
  background: #fef3f2;
}

.carry-over-verdict.is-warning {
  color: #b35b00;
  background: #fff8ec;
}

.carry-over-verdict.is-success {
  color: #067647;
  background: #ecfdf3;
}

.carry-over-verdict.is-info {
  color: #475467;
  background: #f2f4f7;
}
</style>
