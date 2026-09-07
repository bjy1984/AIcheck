/**
 * P12 F1 采集补全：结论卡上的采纳/驳回/其实有依据/补充发现、采纳与驳回 AI 建议、
 * 人工结论与 AI 不一致时的"为什么"、证据链驳回原因——全部落到同一张 ai_feedback。
 *
 * 2026-09-06 生产核实：采纳/驳回 AI 建议不落库，证据链驳回发的是常量字符串，
 * 117 次 AI 审查无一条人工纠正可供迭代。这里是飞轮的燃料入口，不是装饰。
 */
import { h, ref } from 'vue'
import { ElInput, ElMessage, ElMessageBox, ElRadio, ElRadioGroup } from 'element-plus'

import { createAiRunFeedbackApi, type AiRunFeedbackPayload } from '@/api/aicheck'
import type { ReviewOpinion } from '@/types/aicheck'

import type { WorkbenchAiFinding } from './workbenchReviewPresentation'

export type ReasonOption = { value: string; label: string }
export type PickedReason = { code: string; label: string; note: string }

export const EVIDENCE_REJECT_REASONS: ReasonOption[] = [
  { value: 'position_wrong', label: '位置错：文件对，但页码或位置不对' },
  { value: 'content_mismatch', label: '内容不符：引用的内容证明不了这一项' },
  { value: 'wrong_file', label: '文件错：引用了不相关的文件' }
]

/** 驳回单条发现的原因，取值直接是后端 AI_FEEDBACK_TYPES。 */
export const FINDING_REJECT_REASONS: ReasonOption[] = [
  { value: 'rejected_false_positive', label: '不是问题：资料实际符合要求' },
  { value: 'wrong_evidence', label: '证据引用错：指向的文件或位置不对' },
  { value: 'wrong_severity', label: '严重度不对：问题存在但轻重判错' },
  { value: 'hallucination', label: '无中生有：资料里没有这回事' }
]

/** 人工结论 ≠ AI 建议时的"为什么"，取值是后端 AI_FEEDBACK_ROOT_CAUSES（七类根因的采集子集）。 */
export const OPINION_OVERRIDE_REASONS: ReasonOption[] = [
  { value: 'evidence_extraction', label: 'AI 读错了资料（证据抽取有误）' },
  { value: 'guard_downgrade', label: 'AI 结论其实有依据，却被判成证据不足' },
  { value: 'rule_logic', label: '规则判定逻辑有误' },
  { value: 'policy', label: '业务口径与 AI 不同' },
  { value: 'data_table', label: '数据表 / 限值有误' },
  { value: 'external_source', label: '外部平台 / 标准源返回有误' },
  { value: 'other', label: '其他' }
]

/**
 * AI 建议展示词 → 人工结论选项，与后端 AI_SUGGESTION_TO_OPINION_RESULT 同一口径。
 * 映射不到的建议（需专业判断 / 执行故障待重试）不预填：兜底成某个具体结论会把语义反过来。
 */
export const AI_RESULT_TO_OPINION: Record<string, ReviewOpinion['result']> = {
  建议满足要求: '满足要求',
  满足要求: '满足要求',
  建议不符合: '需补正',
  需补正: '需补正',
  建议不适用: '不适用',
  不适用: '不适用',
  证据不足: '证据不足'
}

/** 单选 + 可选补充说明的原因弹窗；取消返回 undefined。 */
export const pickReason = async (options: {
  title: string
  message: string
  reasons: ReasonOption[]
  allowNote?: boolean
  notePlaceholder?: string
  confirmText?: string
}): Promise<PickedReason | undefined> => {
  const selected = ref(options.reasons[0]?.value || '')
  const note = ref('')
  try {
    await ElMessageBox({
      title: options.title,
      showCancelButton: true,
      confirmButtonText: options.confirmText || '确认',
      cancelButtonText: '取消',
      closeOnClickModal: false,
      message: () =>
        h('div', { class: 'ai-reason-picker' }, [
          h('p', { class: 'ai-reason-picker__message' }, options.message),
          h(
            ElRadioGroup,
            {
              modelValue: selected.value,
              'onUpdate:modelValue': (value: string | number | boolean | undefined) => {
                selected.value = String(value ?? '')
              },
              class: 'ai-reason-picker__group'
            },
            () =>
              options.reasons.map((reason) =>
                h(ElRadio, { value: reason.value, key: reason.value }, () => reason.label)
              )
          ),
          options.allowNote
            ? h(ElInput, {
                modelValue: note.value,
                'onUpdate:modelValue': (value: string) => {
                  note.value = value
                },
                type: 'textarea',
                rows: 2,
                maxlength: 300,
                placeholder: options.notePlaceholder || '补充说明（可不填）',
                class: 'ai-reason-picker__note'
              })
            : null
        ])
    })
  } catch {
    return undefined
  }
  const picked = options.reasons.find((reason) => reason.value === selected.value)
  if (!picked) return undefined
  return { code: picked.value, label: picked.label, note: note.value.trim() }
}

export type AiFeedbackDecision = 'accept' | 'reject' | 'supported'

export const useAiFindingFeedback = (ctx: {
  runId: () => string
  etag: () => string | undefined
  ensureWritable: () => boolean
  reload: () => Promise<unknown>
}) => {
  const decisions = ref<Record<string, AiFeedbackDecision>>({})
  const busy = ref(false)

  const record = async (payload: AiRunFeedbackPayload) => {
    const runId = ctx.runId()
    if (!runId) {
      ElMessage.warning('当前没有可关联的节点 AI 复核运行，请先发起 AI 复核再记录反馈。')
      return false
    }
    busy.value = true
    try {
      const res = await createAiRunFeedbackApi(runId, payload, { etag: ctx.etag() })
      if (!res) {
        ElMessage.error('反馈记录失败，请刷新后重试。')
        return false
      }
      return true
    } catch {
      ElMessage.error('反馈记录失败，请刷新后重试。')
      return false
    } finally {
      busy.value = false
    }
  }

  const handleFindingDecision = async (
    finding: WorkbenchAiFinding,
    decision: 'accept' | 'reject'
  ) => {
    if (!ctx.ensureWritable()) return
    if (decision === 'accept') {
      const ok = await record({
        feedbackType: 'accepted',
        accepted: true,
        findingId: finding.id,
        comment: finding.title,
        source: 'finding_card'
      })
      if (ok) {
        decisions.value = { ...decisions.value, [finding.id]: 'accept' }
        ElMessage.success('已记录：采纳该条发现')
      }
      return
    }
    const reason = await pickReason({
      title: '驳回该条发现',
      message: `「${finding.title || finding.description}」为什么不成立？该选择会进入 AI 纠正记录。`,
      reasons: FINDING_REJECT_REASONS,
      allowNote: true,
      confirmText: '确认驳回'
    })
    if (!reason) return
    const ok = await record({
      feedbackType: reason.code,
      accepted: false,
      findingId: finding.id,
      comment: reason.note ? `${reason.label}：${reason.note}` : reason.label,
      source: 'finding_card'
    })
    if (ok) {
      decisions.value = { ...decisions.value, [finding.id]: 'reject' }
      ElMessage.success('已记录：驳回该条发现')
    }
  }

  const handleClaimSupported = async (finding: WorkbenchAiFinding, claim: string) => {
    if (!ctx.ensureWritable()) return
    let location = ''
    try {
      const prompt = await ElMessageBox.prompt(
        `「${claim}」其实在资料里有依据？请写明在哪份文件、第几页，守卫语料会据此迭代。`,
        '其实有依据',
        {
          confirmButtonText: '记录',
          cancelButtonText: '取消',
          inputType: 'textarea',
          inputPlaceholder: '例如：焊工证扫描件 第 2 页 项目代号栏',
          inputValidator: (value) => (value.trim().length >= 2 ? true : '请写明资料位置')
        }
      )
      location = prompt.value.trim()
    } catch {
      return
    }
    const ok = await record({
      feedbackType: 'guard_false_downgrade',
      accepted: false,
      findingId: finding.id,
      claim,
      comment: location,
      source: 'insufficient_group'
    })
    if (ok) {
      decisions.value = { ...decisions.value, [`${finding.id}::${claim}`]: 'supported' }
      ElMessage.success('已记录：该断言其实有依据')
    }
  }

  const handleSupplementFinding = async () => {
    if (!ctx.ensureWritable()) return
    let text = ''
    try {
      const prompt = await ElMessageBox.prompt(
        '请描述 AI 没有发现的问题：查到什么 → 差在哪 → 建议怎么做。',
        '补充发现',
        {
          confirmButtonText: '记录',
          cancelButtonText: '取消',
          inputType: 'textarea',
          inputPlaceholder: '例如：焊工姜军的证书项目代号不含 6G，而工艺卡要求全位置',
          inputValidator: (value) => (value.trim().length >= 4 ? true : '请至少填写 4 个字符')
        }
      )
      text = prompt.value.trim()
    } catch {
      return
    }
    const ok = await record({
      feedbackType: 'missed_issue',
      accepted: false,
      comment: text,
      source: 'conclusion_card'
    })
    if (ok) ElMessage.success('已记录补充发现，将进入 AI 纠正样本')
  }

  /** 采纳 / 驳回整次 AI 建议：原来只写审计日志，现在同时写 ai_feedback。 */
  const recordRunDecision = (accepted: boolean, comment: string) =>
    record({
      feedbackType: accepted ? 'accepted' : 'edited',
      accepted,
      comment,
      source: accepted ? 'adopt_suggestion' : 'reject_suggestion'
    })

  const askOverrideReason = (suggested: string, human: string) =>
    pickReason({
      title: '人工结论与 AI 建议不一致',
      message: `AI 建议「${suggested}」，您的结论是「${human}」。为什么不一致？（单选，进入 AI 纠正记录）`,
      reasons: OPINION_OVERRIDE_REASONS,
      allowNote: true,
      confirmText: '继续保存'
    })

  const recordOpinionOverride = (reason: PickedReason, suggested: string, human: string) =>
    record({
      feedbackType: 'edited',
      accepted: false,
      rootCause: reason.code,
      comment: reason.note ? `${reason.label}：${reason.note}` : reason.label,
      suggestedResult: suggested,
      humanResult: human,
      source: 'review_opinion'
    })

  return {
    decisions,
    busy,
    handleFindingDecision,
    handleClaimSupported,
    handleSupplementFinding,
    recordRunDecision,
    askOverrideReason,
    recordOpinionOverride
  }
}
