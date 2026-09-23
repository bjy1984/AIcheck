<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CircleCloseFilled } from '@element-plus/icons-vue'
import { ElButton, ElIcon } from 'element-plus'

import {
  buildWorkbenchAiConclusion,
  canShowWorkbenchAiConclusion,
  CHECK_OUTCOME_LABELS,
  workbenchFindingDisplay,
  type WorkbenchAiCheckOutcome,
  type WorkbenchAiFinding,
  type WorkbenchAiGroundedFact,
  type WorkbenchAiUnscoredFact,
  type WorkbenchAiUnscoredField,
  type WorkbenchAiFindingGroupKey,
  type WorkbenchAiPresentation
} from '../workbenchReviewPresentation'
import { friendlyMaterialType, friendlyRuleCode } from './auditLabels'
import AuditStatusTag from './AuditStatusTag.vue'
import CertificateVerificationCard from './CertificateVerificationCard.vue'

const props = withDefaults(
  defineProps<{
    presentation: WorkbenchAiPresentation
    history: WorkbenchAiPresentation[]
    /** 监检可操作（采纳/驳回/其实有依据/补充发现）。施工方与只读视图为 false。 */
    canAct?: boolean
    acting?: boolean
    /** 本次会话里已记录的发现级反馈，键为 findingId 或 `${findingId}::${claim}`。 */
    decisions?: Record<string, 'accept' | 'reject' | 'supported' | 'confirmed'>
    /** 最新一次复核失败、下面显示的是上一次成功结果时的说明。 */
    staleNotice?: string
  }>(),
  { canAct: false, acting: false, decisions: () => ({}), staleNotice: '' }
)

const emit = defineEmits<{
  openFile: [fileId: string]
  findingDecision: [finding: WorkbenchAiFinding, decision: 'accept' | 'reject']
  claimSupported: [finding: WorkbenchAiFinding, claim: string]
  supplementFinding: []
  returnCorrection: [finding: WorkbenchAiFinding]
  /** 逐项核查为空时的出口：一键分析不跑确定性核查，得让人在这里直接发起节点复核。 */
  startNodeReview: []
  /** 逐项核查里「核对无误」：把引擎没给分的字段落成人工确认，下次跑就有分。 */
  confirmFact: [
    outcome: WorkbenchAiCheckOutcome,
    fact: WorkbenchAiUnscoredFact,
    /** null：这条事实没有抽取字段（例如设计章），按 fact.factPath 确认。 */
    field: WorkbenchAiUnscoredField | null
  ]
}>()

/**
 * 结论卡只在"已完成"的运行上推导：分析中/失败时没有可靠的发现集合，
 * 推导出的"未见问题"会误导——那时只显示状态横幅。
 */
/**
 * 引用依据分三档标出来（后端 clauseRefs.sourceKind）：
 * 登记过版本的标准、本工程上传的资料原文、标准名对得上但版本没登记。
 * 2026-09-13 线上审计：P-2026-ECD202 的 296 条引用里 127 条没有标准号，
 * 引得最多的是「地上甲类储罐区2（含泵区）施工图.pdf」——那不是规范要求。
 */
const CLAUSE_KIND_LABELS: Record<string, string> = {
  standard: '标准条款',
  document: '资料原文',
  unregistered_standard: '标准·版本未登记'
}

const conclusion = computed(() =>
  !canShowWorkbenchAiConclusion(props.presentation)
    ? undefined
    : buildWorkbenchAiConclusion({
        findings: props.presentation.findings,
        deterministicResult: props.presentation.deterministicResult
      })
)

const GROUP_META: Record<
  WorkbenchAiFindingGroupKey,
  { title: string; hint: string; tone: 'red' | 'orange' | 'gray' | 'green' | 'blue' }
> = {
  needAction: { title: '需处理', hint: '通过证据核对，严重度高', tone: 'red' },
  confirm: { title: '待确认', hint: '通过证据核对，需人工判断', tone: 'blue' },
  insufficient: { title: '证据不足', hint: '模型结论未获证据支持，已折叠', tone: 'orange' },
  passed: { title: '通过', hint: '查到了、符合要求；证据在下方，仍需人工确认', tone: 'green' }
}

const displayGroup = (key: WorkbenchAiFindingGroupKey) =>
  (conclusion.value?.groups[key] || []).map((finding) => ({
    ...workbenchFindingDisplay(finding),
    raw: finding,
    typeLabel: finding.typeLabel,
    actionLabel: finding.actionLabel || '',
    policyPending: finding.policyPending === true,
    policyName: finding.policyName || '',
    unsupportedClaims: finding.unsupportedClaims || [],
    modelTitle: finding.modelTitle || '',
    modelDescription: finding.modelDescription || '',
    unverified: finding.unverified === true,
    /** 正文超过三行（按 90 字估）才给"展开"。 */
    clampable: String(finding.description || '').length > 90
  }))

const needActionFindings = computed(() => displayGroup('needAction'))
const confirmFindings = computed(() => displayGroup('confirm'))
const insufficientFindings = computed(() => displayGroup('insufficient'))
const passedFindings = computed(() => displayGroup('passed'))
const groupFindings = (key: 'needAction' | 'confirm' | 'passed') =>
  key === 'needAction'
    ? needActionFindings.value
    : key === 'confirm'
      ? confirmFindings.value
      : passedFindings.value

/** 只有当前面板还没形成结论卡（旧路径：自由文本解析）时，才退回平铺列表。 */
const flatFindings = computed(() =>
  conclusion.value ? [] : props.presentation.findings.map(workbenchFindingDisplay)
)

const insufficientOpen = ref(false)
const expandedFindings = ref<Set<string>>(new Set())
const expandedModelText = ref<Set<string>>(new Set())

watch(
  () => props.presentation.runId,
  () => {
    insufficientOpen.value = false
    expandedFindings.value = new Set()
    expandedModelText.value = new Set()
  }
)

const toggle = (bucket: 'finding' | 'model', id: string) => {
  const target = bucket === 'finding' ? expandedFindings : expandedModelText
  const next = new Set(target.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  target.value = next
}

/** 与 aiFindingFeedback.factDecisionKey 同一口径：本次会话里点过「核对无误」的事实。 */
const factConfirmed = (fact: WorkbenchAiGroundedFact, fieldName?: string) =>
  props.decisions[fieldName ? `fact::${fact.factId}::${fieldName}` : `fact::${fact.factId}`] ===
  'confirmed'

/**
 * 模型自评的置信度直接印成「置信度 50%」会被当成校准过的概率读——它不是，
 * 它既不代表证据强弱也不代表正确率。折成三档，并在 title 里说清它是什么。
 */
const modelCertainty = (percent?: number) => {
  if (typeof percent !== 'number' || Number.isNaN(percent)) return ''
  if (percent >= 80) return '较高'
  if (percent >= 50) return '一般'
  return '较低'
}

const decisionLabel = (id: string) => {
  const decision = props.decisions[id]
  return decision === 'accept' ? '已采纳' : decision === 'reject' ? '已驳回' : ''
}

/** 先看要处理的，再看通过的：不符合 → 需人工判断 → 证据不足 → 执行故障 → 不适用 → 通过。 */
const CHECK_OUTCOME_ORDER = [
  'failed',
  'human_review_required',
  'evidence_insufficient',
  'execution_error',
  'not_applicable',
  'passed'
]
/**
 * 颜色口径（2026-09-13 用户定）：已确认/通过=绿，证据不足=黄，错误/不符合=红。
 * 「需人工判断」另给蓝色：它和「证据不足」是两回事——前者证据齐了等人拍板，
 * 后者是缺东西；都涂黄就分不出该补件还是该判断。
 */
const CHECK_OUTCOME_TONES: Record<string, 'red' | 'orange' | 'gray' | 'green' | 'blue'> = {
  failed: 'red',
  execution_error: 'red',
  evidence_insufficient: 'orange',
  human_review_required: 'blue',
  not_applicable: 'gray',
  passed: 'green'
}

const checkOutcomeRank = (outcome: WorkbenchAiCheckOutcome) => {
  if (outcome.secondOpinion?.priority === 'disagreement') return -2
  if (outcome.secondOpinion?.priority === 'low_confidence') return -1
  const index = CHECK_OUTCOME_ORDER.indexOf(outcome.result)
  return index < 0 ? CHECK_OUTCOME_ORDER.length : index
}

const sortedCheckOutcomes = computed(() =>
  [...props.presentation.checkOutcomes].sort(
    (left, right) => checkOutcomeRank(left) - checkOutcomeRank(right)
  )
)

/** 「共 N 项：通过 3、证据不足 2」——按上面的顺序报，通过的也报。 */
const checkOutcomeTally = computed(() => {
  const counts = new Map<string, number>()
  props.presentation.checkOutcomes.forEach((item) =>
    counts.set(item.result, (counts.get(item.result) || 0) + 1)
  )
  return CHECK_OUTCOME_ORDER.filter((result) => counts.has(result)).map((result) => ({
    result,
    label: CHECK_OUTCOME_LABELS[result] || result,
    count: counts.get(result) || 0
  }))
})

/**
 * 同一次锚定门的事实对本节点每个原子项都一样，逐项渲染就是同一组引文抄五遍
 * （2026-09-12 线上实测：节点 1 五项 × 6 条引文 = 26 行重复）。按 factId 去重列一次。
 */
const nodeFacts = computed(() => {
  const seen = new Map<string, WorkbenchAiGroundedFact>()
  props.presentation.checkOutcomes.forEach((outcome) =>
    outcome.facts.forEach((fact) => {
      if (!seen.has(fact.factId)) seen.set(fact.factId, fact)
    })
  )
  return [...seen.values()]
})

/** 没给分、且能人工确认的事实（按 factId 找回它的字段与 factPath）。 */
const unscoredByFactId = computed(() => {
  const seen = new Map<
    string,
    { fact: WorkbenchAiUnscoredFact; outcome: WorkbenchAiCheckOutcome }
  >()
  props.presentation.checkOutcomes.forEach((outcome) =>
    outcome.unscoredFacts.forEach((fact) => {
      if (!seen.has(fact.factId)) seen.set(fact.factId, { fact, outcome })
    })
  )
  return seen
})

const nodeUnscoredCount = computed(() => nodeFacts.value.filter((fact) => !fact.scored).length)

/**
 * 事实按类型归组、每组默认只展开三条。
 *
 * 2026-09-13 用户实测节点 26：56 条 `r26-designRequirements-N`，引文是 OCR 把 BOM
 * 表头读坏后的 `{"BOM A_12": "无缝钢管", "0.275": "0.8M"}`——监检看不懂，也没有一条
 * 是他要核的东西。同类事实堆在一起只需要说清「有多少条、长什么样」，要逐条看再展开。
 */
const FACT_PREVIEW = 3
const expandedFactGroups = ref<Set<string>>(new Set())

/**
 * 认不出业务标识的事实不逐条列。
 *
 * 2026-09-13 线上实测节点 26：56 条事实全叫「设计要求」，没有编号、没有牌号，引文是
 * OCR 把管道特性表读坏后的表头配对（`操作压力：操作温度`）。这种行监检核不了，
 * 列 56 条只是把真正要看的东西挤下去；如实说有多少条、让他点开原件看。
 */
/** 老留痕里的事实标签是 `r29-wpsItems-7` 这种 factId；按类型段翻成中文，不必重跑。 */
const FACT_TYPE_NAMES: Record<string, string> = {
  certificates: '焊工证',
  workItems: '施焊记录',
  weldingRecords: '焊接记录',
  wpsItems: '焊接工艺规程 WPS',
  pqrItems: '工艺评定报告 PQR',
  qualityCertificates: '焊材质量证明书',
  designRequirements: '设计要求',
  physicalItems: '焊材实物记录',
  managementRecords: '焊材管理记录',
  fitUpRecords: '管道组对记录',
  appearanceRecords: '外观检查记录',
  repairRecords: '返修记录',
  procedureCards: '热处理工艺卡',
  qualificationReports: '热处理评定报告',
  weldItems: '焊口',
  instrumentRecords: '测温仪表记录',
  temperaturePointLayouts: '测温点布置',
  heatTreatmentReports: '热处理报告',
  hardnessReports: '硬度检测报告',
  // r14/r15/r16-r18 的记录种类：这些事实后端根本不写 label（见 r15_facts.claimed_facts），
  // 全靠这张表按 factId 的类型段翻。少一个就直接把 `design_item` 印到界面上。
  approval: '批准文件',
  arrival_acceptance: '到货验收记录',
  arrival_inspection: '到货检验记录',
  certificate: '证书',
  complete_machine_inspection: '整机检验记录',
  design_item: '设计元件',
  factory_report: '出厂报告',
  inventory: '台账',
  item: '条目',
  lot: '批次',
  manufacturing_license: '制造单位许可证',
  material_ndt: '材料无损检测报告',
  material_retest: '材料复验报告',
  pipeline_characteristic: '管道特性表条目',
  quality_certificate: '产品质量证明书',
  record: '记录',
  report: '报告',
  sampling_witness: '抽样见证记录',
  special_report: '专项报告',
  substitution: '材料代用记录',
  supervision_certificate: '监督检验证书',
  type_test_report: '型式试验报告',
  // r16-r23 用连字符；键要加引号
  'acceptance-record': '到货验收记录',
  'actual-usage': '实际使用记录',
  'design-item': '设计元件',
  'material-data': '材料数据',
  'material-inventory': '材料台账',
  'material-ndt-report': '材料无损检测报告',
  'quality-certificate': '产品质量证明书',
  'retest-report': '复验报告',
  'technical-review': '技术评审记录',
  'transfer-record': '材料移植记录',
  'type-test': '型式试验报告',
  'valve-construction': '阀门施工记录',
  'valve-lot': '阀门批次',
  'valve-test': '阀门试验记录',
  'witness-record': '见证记录'
}

const factDisplayLabel = (fact: WorkbenchAiGroundedFact) => {
  if (fact.label && fact.label !== fact.factId) {
    // 老留痕的标签开头是证书类型代号（`design_license TS1844171-2028`），翻掉再显示
    const [head, ...rest] = fact.label.split(' ')
    const named = friendlyMaterialType(head)
    return named && named !== head ? [named, ...rest].join(' ') : fact.label
  }
  const type = fact.factId.replace(/^r\d+-/, '').replace(/-\d+$/, '')
  return FACT_TYPE_NAMES[type] || type || fact.factId
}

/** 老留痕的引文还是 json.dumps(row)：那是给机器看的，别端到监检面前。 */
const isRawQuote = (fact: WorkbenchAiGroundedFact) =>
  fact.evidence.length > 0 && fact.evidence.every((item) => item.quotedText.trim().startsWith('{'))

/**
 * 一条事实要值得单独列，得让人分得清它是哪一条。
 *
 * 2026-09-13 用户实测节点 29：38 条 `r29-wpsItems-N`，值全是同一个文件标题
 * 「焊接工艺评定任务书」，引文是 OCR 把试验报告表头当成列名的 JSON。同名同值的只留
 * 一条并标出还有多少条；引文还是 JSON 的整条不列——看不懂的东西列 38 遍不叫「有依据」。
 */
const listableFacts = computed(() => {
  const seen = new Map<
    string,
    { fact: WorkbenchAiGroundedFact; label: string; sameCount: number }
  >()
  nodeFacts.value.forEach((fact) => {
    if (!(fact.value || fact.platformVerified || !fact.scored) || isRawQuote(fact)) return
    const label = factDisplayLabel(fact)
    const key = `${label}|${fact.value}`
    const existing = seen.get(key)
    if (existing) {
      existing.sameCount += 1
      if (fact.platformVerified && !existing.fact.platformVerified) existing.fact = fact
      return
    }
    seen.set(key, { fact, label, sameCount: 1 })
  })
  return [...seen.values()]
})

const identifiedFacts = computed(() => listableFacts.value.map((item) => item.fact))
const unidentifiedFacts = computed(() => {
  const listed = new Set(identifiedFacts.value.map((fact) => fact.factId))
  return nodeFacts.value.filter((fact) => !listed.has(fact.factId))
})

const sameFactCount = (fact: WorkbenchAiGroundedFact) =>
  listableFacts.value.find((item) => item.fact.factId === fact.factId)?.sameCount ?? 1
const unidentifiedFiles = computed(() => {
  // 按文件名去重：同一份资料的多个版本 documentId 不同，按 id 去重会把同一个文件名列两遍。
  const seen = new Map<string, string>()
  unidentifiedFacts.value.forEach((fact) =>
    fact.evidence.forEach((item) => {
      if (item.documentId && item.fileName && !seen.has(item.fileName)) {
        seen.set(item.fileName, item.documentId)
      }
    })
  )
  return [...seen.entries()].map(([fileName, documentId]) => ({ documentId, fileName }))
})

const factGroups = computed(() => {
  const groups = new Map<string, WorkbenchAiGroundedFact[]>()
  listableFacts.value.forEach(({ fact, label }) => {
    // 「焊工证 姜军」归到「焊工证」；老留痕按 factId 的类型段归。
    const key = label.split(' ')[0]
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)?.push(fact)
  })
  return [...groups.entries()].map(([label, facts]) => ({
    label,
    facts,
    // 平台核过、没给分、有值的排前面：要人看的排在前三条里
    visible: expandedFactGroups.value.has(label)
      ? facts
      : [...facts]
          .sort(
            (left, right) =>
              Number(right.platformVerified) - Number(left.platformVerified) ||
              Number(!right.scored) - Number(!left.scored) ||
              Number(Boolean(right.value)) - Number(Boolean(left.value))
          )
          .slice(0, FACT_PREVIEW),
    hidden: expandedFactGroups.value.has(label) ? 0 : Math.max(0, facts.length - FACT_PREVIEW)
  }))
})

const toggleFactGroup = (label: string) => {
  const next = new Set(expandedFactGroups.value)
  if (next.has(label)) next.delete(label)
  else next.add(label)
  expandedFactGroups.value = next
}
const confirmable = (fact: WorkbenchAiGroundedFact) => unscoredByFactId.value.get(fact.factId)?.fact
const confirmableOutcome = (fact: WorkbenchAiGroundedFact) =>
  unscoredByFactId.value.get(fact.factId)?.outcome

/** 没跑确定性核查、模型也没写符合项时显示「—」：0 会被读成「查过了，一条都没通过」。 */
const passedCountHint = computed(() =>
  sortedCheckOutcomes.value.length
    ? '本次逐项核查判定为通过的项数'
    : '本次只做了模型通读，未执行确定性核查——发起节点复核才有逐项通过/不通过'
)

const checkOutcomeLabel = (result: string) => CHECK_OUTCOME_LABELS[result] || result || '未记录'
const checkOutcomeTone = (result: string) => CHECK_OUTCOME_TONES[result] || 'gray'

const pageLabel = (pages: number[]) => (pages.length ? `第 ${pages.join('、')} 页` : '')

/** 规则依据：有原文就印原文，否则把规则键翻成人话（`welder-qualification` → 焊工资格）。 */
const ruleLabel = (rule: Record<string, unknown>) => {
  const text = String(rule.text || '').trim()
  if (text) return text
  const code = String(rule.ruleCode || rule.source || '')
  return code ? friendlyRuleCode(code) : '规则依据'
}
</script>

<template>
  <section id="inspection-audit-panel-ai_review" class="card workbench-ai-review-panel">
    <div class="card-head ai-panel-head">
      <div>
        <h2>一、AI 审查</h2>
        <div class="sub">本次及历史 AI 复核结果</div>
      </div>
      <div class="ai-run-meta">
        <AuditStatusTag :tone="presentation.statusTone" round>
          {{ presentation.statusLabel }}
        </AuditStatusTag>
        <small v-if="presentation.meta">{{ presentation.meta }}</small>
      </div>
    </div>

    <div class="card-body ai-panel-body">
      <!-- 基础设施抖动不该让人丢掉上一次的结论；但也不能假装最新那次没失败 -->
      <p v-if="staleNotice" class="ai-stale-notice" role="status">{{ staleNotice }}</p>
      <div v-if="presentation.errorMessage" class="ai-status-banner" role="alert">
        <div class="ai-status-banner__icon" aria-hidden="true">
          <ElIcon><CircleCloseFilled /></ElIcon>
        </div>
        <div class="ai-status-banner__content">
          <strong>{{ presentation.statusLabel }}</strong>
          <p class="ai-error-message">{{ presentation.errorMessage }}</p>
        </div>
      </div>

      <article
        :class="['ai-current-result', `is-${presentation.statusTone}`]"
        aria-label="本次 AI 复核结果"
      >
        <div class="ai-current-result-head">
          <div>
            <span>本次复核</span>
            <strong>{{ presentation.sourceLabel }}</strong>
          </div>
          <AuditStatusTag :tone="presentation.statusTone" round>
            {{ presentation.resultLabel }}
          </AuditStatusTag>
        </div>

        <!-- 结论卡：要不要管 / 去查哪份 / 做什么，一屏回答（P9 R1，契约 12.3） -->
        <section
          v-if="conclusion"
          :class="['ai-conclusion', `is-${conclusion.tone}`]"
          aria-label="AI 结论卡"
        >
          <div class="ai-conclusion-head">
            <AuditStatusTag :tone="conclusion.tone" round>{{ conclusion.verdict }}</AuditStatusTag>
            <strong class="ai-conclusion-headline">{{ conclusion.headline }}</strong>
            <span class="ai-conclusion-note">AI 建议，未经人工确认</span>
            <span
              v-if="presentation.partialCoverageLabel"
              class="ai-conclusion-note is-partial"
              title="修复与升级模型重试后仍失败的证据分片，这些证据没有被 AI 审到"
            >
              {{ presentation.partialCoverageLabel }}
            </span>
          </div>
          <dl class="ai-conclusion-counts">
            <div class="is-red">
              <dt>需处理</dt>
              <dd>{{ conclusion.counts.needAction }}</dd>
            </div>
            <div class="is-blue">
              <dt>待确认</dt>
              <dd>{{ conclusion.counts.confirm }}</dd>
            </div>
            <div class="is-orange">
              <dt>证据不足</dt>
              <dd>{{ conclusion.counts.insufficient }}</dd>
            </div>
            <div class="is-green">
              <dt>通过</dt>
              <dd :title="passedCountHint">
                {{
                  conclusion.counts.passed || sortedCheckOutcomes.length
                    ? conclusion.counts.passed
                    : '—'
                }}
              </dd>
            </div>
          </dl>
          <ul v-if="conclusion.keyFacts.length" class="ai-conclusion-facts">
            <li v-for="(fact, index) in conclusion.keyFacts" :key="index">
              <span>{{ fact.text }}</span>
              <small v-if="fact.location">{{ fact.location }}</small>
            </li>
          </ul>
          <div class="ai-conclusion-action">
            <span>建议动作</span>
            <strong>{{ conclusion.action }}</strong>
            <small v-if="conclusion.deterministicLabel">{{ conclusion.deterministicLabel }}</small>
            <ElButton
              v-if="canAct"
              size="small"
              text
              bg
              :disabled="acting"
              class="ai-conclusion-supplement"
              @click="emit('supplementFinding')"
            >
              补充 AI 未发现的问题
            </ElButton>
          </div>
        </section>

        <!-- 逐项核查：通过的也要看得见，否则「没报问题」和「没查」分不开 -->
        <section v-if="conclusion" class="ai-check-outcomes" aria-label="逐项核查结果">
          <div class="ai-check-outcomes-head">
            <strong>逐项核查</strong>
            <span v-if="sortedCheckOutcomes.length">共 {{ sortedCheckOutcomes.length }} 项</span>
            <small v-if="sortedCheckOutcomes.length">
              {{ checkOutcomeTally.map((item) => `${item.label} ${item.count}`).join('、') }}
            </small>
            <small v-else>
              本次运行没有留下逐项核查记录：一键分析只让模型通读资料，不执行确定性核查。
            </small>
            <ElButton
              v-if="!sortedCheckOutcomes.length && canAct"
              size="small"
              type="primary"
              text
              bg
              :disabled="acting"
              @click="emit('startNodeReview')"
            >
              发起节点复核
            </ElButton>
          </div>
          <ul v-if="sortedCheckOutcomes.length">
            <li v-for="outcome in sortedCheckOutcomes" :key="outcome.atomicCheckId">
              <AuditStatusTag :tone="checkOutcomeTone(outcome.result)" round>
                {{ checkOutcomeLabel(outcome.result) }}
              </AuditStatusTag>
              <AuditStatusTag
                v-if="outcome.secondOpinion"
                :tone="outcome.secondOpinion.needsHumanReview ? 'orange' : 'green'"
                round
              >
                {{ outcome.secondOpinion.agreesWithRuleEngine
                  ? outcome.secondOpinion.needsHumanReview ? '第二意見把握較低，建議人工' : '第二意見一致'
                  : '第二意見分歧，建議人工' }}
              </AuditStatusTag>
              <span>{{ outcome.name }}</span>
              <small>{{ outcome.atomicCheckId }}</small>
              <!-- 依据与证据：通过/不通过/需人工都列，监检才能核对而不是只看一个标签 -->
              <div
                v-if="outcome.reason || outcome.checks.length || outcome.facts.length"
                class="ai-outcome-basis"
              >
                <p v-if="outcome.reason" class="ai-outcome-reason">
                  <span>原因</span>{{ outcome.reason }}
                </p>
                <ul v-if="outcome.checks.length" class="ai-outcome-checks" aria-label="判定依据">
                  <li v-for="check in outcome.checks" :key="`${check.tool}:${check.code}`">
                    <i
                      :class="['ai-check-mark', check.passed ? 'is-pass' : 'is-fail']"
                      aria-hidden="true"
                    >
                      {{ check.passed ? '✓' : check.missing ? '－' : '✗' }}
                    </i>
                    <span class="ai-check-label">{{ check.label }}</span>
                    <small v-if="check.actual || check.expected">
                      <template v-if="check.actual">实际 {{ check.actual }}</template>
                      <template v-if="check.actual && check.expected"> · </template>
                      <template v-if="check.expected">要求 {{ check.expected }}</template>
                    </small>
                  </li>
                </ul>
              </div>
            </li>
          </ul>
          <!-- 事实与证据按节点列一次：同一次锚定的结果对每个原子项都一样，逐项重复就是同一组引文抄五遍 -->
          <div v-if="nodeFacts.length" class="ai-outcome-facts-block">
            <div class="ai-check-outcomes-head">
              <strong>事实与证据</strong>
              <span v-if="identifiedFacts.length">共 {{ identifiedFacts.length }} 条</span>
              <span v-else>未识别出可核事实</span>
              <small v-if="nodeUnscoredCount">
                其中 {{ nodeUnscoredCount }} 条引擎未给分，核对无误后下次复核即可计分
              </small>
            </div>
            <template v-for="group in factGroups" :key="group.label">
              <div v-if="factGroups.length > 1" class="ai-fact-group-head">
                <strong>{{ group.label }}</strong>
                <span>{{ group.facts.length }} 条</span>
              </div>
              <ul class="ai-outcome-facts">
                <li
                  v-for="fact in group.visible"
                  :key="fact.factId"
                  :class="{ 'is-platform-verified': fact.platformVerified }"
                >
                  <div class="ai-outcome-fact-head">
                    <span class="ai-unscored-fact-label">{{ factDisplayLabel(fact) }}</span>
                    <!-- 标签里已经含了这个值就别再印一遍（「焊工证 李卫伍 李卫伍」） -->
                    <span
                      v-if="fact.value && !factDisplayLabel(fact).includes(fact.value)"
                      class="ai-unscored-fact-value"
                    >
                      {{ fact.value }}
                    </span>
                    <small v-if="sameFactCount(fact) > 1" class="ai-fact-same-count">
                      另有 {{ sameFactCount(fact) - 1 }} 条同样内容
                    </small>
                    <!-- 平台核到的那几条要一眼看出来：登记原文比 OCR 可信 -->
                    <small
                      v-if="fact.platformVerified"
                      class="ai-fact-platform"
                      title="公示平台按证件号查到并与本条一致，有效期与合格项目以登记为准"
                    >
                      平台已核验
                    </small>
                    <small v-if="!fact.scored" class="ai-fact-unscored">引擎未给分</small>
                    <template v-if="!fact.scored && confirmable(fact)">
                      <template
                        v-for="field in confirmable(fact)!.fields"
                        :key="`${field.documentVersionId}:${field.fieldName}`"
                      >
                        <small v-if="field.humanCorrected" class="ai-fact-confirmed">
                          {{ field.fieldName }} 已人工确认
                        </small>
                        <small
                          v-else-if="factConfirmed(fact, field.fieldName)"
                          class="ai-fact-confirmed"
                        >
                          {{ field.fieldName }} 已记录，下次复核生效
                        </small>
                        <ElButton
                          v-else-if="canAct"
                          size="small"
                          text
                          bg
                          :disabled="acting"
                          :title="field.quotedText"
                          @click="
                            emit(
                              'confirmFact',
                              confirmableOutcome(fact)!,
                              confirmable(fact)!,
                              field
                            )
                          "
                        >
                          核对无误：{{ field.fieldName }}
                        </ElButton>
                      </template>
                      <!-- 印章一类没有抽取字段的事实：按事实路径确认，否则这一项永远出不去「需人工判断」 -->
                      <template
                        v-if="!confirmable(fact)!.fields.length && confirmable(fact)!.factPath"
                      >
                        <small v-if="factConfirmed(fact)" class="ai-fact-confirmed">
                          已记录，下次复核生效
                        </small>
                        <ElButton
                          v-else-if="canAct"
                          size="small"
                          text
                          bg
                          :disabled="acting"
                          @click="
                            emit('confirmFact', confirmableOutcome(fact)!, confirmable(fact)!, null)
                          "
                        >
                          核对无误
                        </ElButton>
                      </template>
                    </template>
                  </div>
                  <ul class="ai-outcome-quotes">
                    <li v-for="item in fact.evidence" :key="item.evidenceRefId">
                      <q :title="item.quotedText">{{ item.quotedText }}</q>
                      <small v-if="item.source === 'cnse_platform'">公示平台登记</small>
                      <!-- 点文件名打开原件：核对引文得看得到原图，不能只给一行字 -->
                      <button
                        v-else-if="item.documentId"
                        type="button"
                        class="ai-quote-source"
                        :title="`打开 ${item.fileName || '原件'}`"
                        @click="emit('openFile', item.documentId)"
                      >
                        {{ item.fileName || '打开原件'
                        }}<template v-if="item.pageNo"> · 第 {{ item.pageNo }} 页</template>
                      </button>
                      <small v-else>
                        {{ item.fileName
                        }}<template v-if="item.pageNo"> · 第 {{ item.pageNo }} 页</template>
                      </small>
                      <small v-if="item.humanCorrected">已人工确认</small>
                    </li>
                  </ul>
                </li>
                <li v-if="group.hidden" class="ai-fact-more">
                  <button type="button" @click="toggleFactGroup(group.label)">
                    还有 {{ group.hidden }} 条同类记录，展开
                  </button>
                </li>
                <li v-else-if="group.facts.length > FACT_PREVIEW" class="ai-fact-more">
                  <button type="button" @click="toggleFactGroup(group.label)">收起</button>
                </li>
              </ul>
            </template>
            <!-- 认不出业务标识的：如实说有多少条，指到原件，不逐条铺 -->
            <p v-if="unidentifiedFacts.length" class="ai-fact-unidentified">
              另有
              {{ unidentifiedFacts.length }}
              条表格记录未能识别出可核字段（编号、牌号、焊口号等）或内容重复，未逐条列出。
              <template v-for="file in unidentifiedFiles" :key="file.documentId">
                <button type="button" @click="emit('openFile', file.documentId)">
                  查看 {{ file.fileName }}
                </button>
              </template>
            </p>
          </div>
        </section>

        <p class="ai-result-summary">{{ presentation.summary }}</p>
        <CertificateVerificationCard
          v-if="presentation.certificateVerification"
          :verification="presentation.certificateVerification"
        />

        <!-- 四组发现：需处理 → 待确认 → 通过 → 证据不足（折叠）。通过的也列全证据，监检才核得了 -->
        <template v-if="conclusion && presentation.findings.length">
          <div
            v-for="groupKey in ['needAction', 'confirm', 'passed'] as const"
            :key="groupKey"
            v-show="groupFindings(groupKey).length"
            class="ai-result-findings"
          >
            <div class="ai-result-findings-head">
              <AuditStatusTag :tone="GROUP_META[groupKey].tone" round>
                {{ GROUP_META[groupKey].title }}
              </AuditStatusTag>
              <span>{{ groupFindings(groupKey).length }} 条</span>
              <small>{{ GROUP_META[groupKey].hint }}</small>
            </div>
            <article
              v-for="(finding, findingIndex) in groupFindings(groupKey)"
              :key="finding.id"
              :class="['ai-finding', `is-${finding.severityTone}`]"
            >
              <div class="ai-finding-head">
                <span class="ai-finding-index">{{ findingIndex + 1 }}</span>
                <h3>{{ finding.title || '审查发现' }}</h3>
                <AuditStatusTag v-if="finding.severityTag" :tone="finding.severityTone" round>
                  {{ finding.severityTag }}
                </AuditStatusTag>
                <span v-if="decisionLabel(finding.id)" class="ai-finding-decision">
                  {{ decisionLabel(finding.id) }}
                </span>
                <span
                  v-if="modelCertainty(finding.confidencePercent)"
                  class="ai-finding-confidence"
                  title="模型对自己这条结论的把握，不是校准过的概率，也不代表证据强弱"
                >
                  模型把握{{ modelCertainty(finding.confidencePercent) }}
                </span>
              </div>
              <div class="ai-finding-chips">
                <span v-if="finding.typeLabel" class="ai-chip">{{ finding.typeLabel }}</span>
                <span v-if="finding.actionLabel" class="ai-chip is-action">
                  {{ finding.actionLabel }}
                </span>
                <span v-if="finding.policyPending" class="ai-chip is-policy">
                  口径待确认{{ finding.policyName ? `：${finding.policyName}` : '' }}
                </span>
                <span v-if="finding.evidenceCount" class="ai-chip">
                  证据 {{ finding.evidenceCount }}
                </span>
                <span v-if="finding.ruleCount" class="ai-chip">规则 {{ finding.ruleCount }}</span>
              </div>
              <p
                :class="[
                  'ai-finding-description',
                  { 'is-clamped': finding.clampable && !expandedFindings.has(finding.id) }
                ]"
              >
                {{ finding.description }}
              </p>
              <button
                v-if="finding.clampable"
                type="button"
                class="ai-link-button"
                @click="toggle('finding', finding.id)"
              >
                {{ expandedFindings.has(finding.id) ? '收起' : '展开全文' }}
              </button>
              <div v-if="finding.evidenceGroups.length" class="ai-evidence-groups">
                <div
                  v-for="group in finding.evidenceGroups"
                  :key="group.fileId || group.fileName"
                  class="ai-evidence-group"
                >
                  <button
                    type="button"
                    class="ai-evidence-file"
                    @click="emit('openFile', group.fileId)"
                  >
                    <span class="ai-evidence-file-icon" aria-hidden="true">▤</span>
                    <span class="ai-evidence-file-name">{{ group.fileName }}</span>
                    <small v-if="group.pages.length">{{ pageLabel(group.pages) }}</small>
                  </button>
                  <ul v-if="group.quotes.length" class="ai-evidence-quotes">
                    <li v-for="quote in group.quotes" :key="quote">{{ quote }}</li>
                  </ul>
                </div>
              </div>
              <!-- 引用依据：标准名 + 章节 + 条款号 + 原文，监检能直接对着查。
                   标准条款和本工程资料原文分开标——混在一起会让人把施工方案当规范要求。 -->
              <ul v-if="finding.clauseRefs.length" class="ai-clause-list" aria-label="引用依据">
                <li v-for="clause in finding.clauseRefs" :key="clause.clauseId">
                  <div class="ai-clause-head">
                    <em :class="`ai-clause-kind is-${clause.sourceKind}`">{{
                      CLAUSE_KIND_LABELS[clause.sourceKind]
                    }}</em>
                    <strong>{{ clause.standardCode || clause.standard || '条款' }}</strong>
                    <span v-if="clause.standardCode && clause.standard">{{ clause.standard }}</span>
                    <span v-if="clause.section">{{ clause.section }}</span>
                    <small v-if="clause.clauseNo">{{ clause.clauseNo }}</small>
                    <small v-if="clause.pageNo">第 {{ clause.pageNo }} 页</small>
                    <!-- 条款原文一显示出来监检就会照着核，引旧版比不显示更糟 -->
                    <strong
                      v-if="clause.superseded"
                      class="ai-clause-superseded"
                      :title="clause.superseded.note"
                    >
                      已被 {{ clause.superseded.supersededBy }} 取代（{{
                        clause.superseded.effectiveFrom
                      }}
                      施行）
                    </strong>
                  </div>
                  <q>{{ clause.text }}</q>
                </li>
              </ul>
              <div v-if="finding.ruleRefs.length" class="ai-rule-list">
                <span v-for="(rule, index) in finding.ruleRefs" :key="index">
                  {{ ruleLabel(rule) }}
                </span>
              </div>
              <div v-if="canAct" class="ai-finding-actions">
                <ElButton
                  size="small"
                  :disabled="acting || Boolean(decisionLabel(finding.id))"
                  @click="emit('findingDecision', finding.raw, 'accept')"
                >
                  采纳
                </ElButton>
                <ElButton
                  size="small"
                  :disabled="acting || Boolean(decisionLabel(finding.id))"
                  @click="emit('findingDecision', finding.raw, 'reject')"
                >
                  驳回
                </ElButton>
                <ElButton
                  v-if="groupKey === 'needAction'"
                  size="small"
                  type="warning"
                  plain
                  :disabled="acting"
                  @click="emit('returnCorrection', finding.raw)"
                >
                  据此退回补正
                </ElButton>
              </div>
            </article>
          </div>

          <div v-if="insufficientFindings.length" class="ai-result-findings ai-insufficient">
            <button
              type="button"
              class="ai-result-findings-head ai-insufficient-toggle"
              :aria-expanded="insufficientOpen"
              @click="insufficientOpen = !insufficientOpen"
            >
              <AuditStatusTag tone="gray" round>{{ GROUP_META.insufficient.title }}</AuditStatusTag>
              <span>{{ insufficientFindings.length }} 条</span>
              <small>
                待核对 {{ conclusion.insufficientClaims.length }} 项 ·
                {{ GROUP_META.insufficient.hint }}
              </small>
              <span class="ai-insufficient-caret">{{ insufficientOpen ? '收起' : '展开' }}</span>
            </button>
            <template v-if="insufficientOpen">
              <ul v-if="conclusion.insufficientClaims.length" class="ai-claim-list">
                <li v-for="item in conclusion.insufficientClaims" :key="item.claim">
                  <span>{{ item.text }}</span>
                  <span
                    v-if="decisions[`${item.findingId}::${item.claim}`] === 'supported'"
                    class="ai-finding-decision"
                  >
                    已标记有依据
                  </span>
                  <ElButton
                    v-else-if="canAct"
                    size="small"
                    text
                    bg
                    :disabled="acting"
                    @click="
                      emit(
                        'claimSupported',
                        insufficientFindings.find((f) => f.id === item.findingId)?.raw ||
                          insufficientFindings[0].raw,
                        item.claim
                      )
                    "
                  >
                    其实有依据
                  </ElButton>
                </li>
              </ul>
              <article
                v-for="finding in insufficientFindings"
                :key="finding.id"
                class="ai-finding is-gray"
              >
                <div class="ai-finding-head">
                  <h3>{{ finding.modelTitle || finding.title || '证据不足，需人工确认' }}</h3>
                  <span v-if="finding.unverified" class="ai-chip is-unverified">未经证据核实</span>
                  <span v-if="finding.typeLabel" class="ai-chip">{{ finding.typeLabel }}</span>
                </div>
                <p class="ai-finding-description">{{ finding.description }}</p>
                <template v-if="finding.modelDescription">
                  <button type="button" class="ai-link-button" @click="toggle('model', finding.id)">
                    {{ expandedModelText.has(finding.id) ? '收起模型原文' : '查看模型原文' }}
                  </button>
                  <blockquote
                    v-if="expandedModelText.has(finding.id)"
                    class="ai-model-text"
                    aria-label="模型原文，未经证据核实"
                  >
                    <span class="ai-chip is-unverified">未经证据核实，不可直接采信</span>
                    <p>{{ finding.modelDescription }}</p>
                  </blockquote>
                </template>
              </article>
            </template>
          </div>
        </template>

        <!-- 旧路径（无结论卡）：平铺列表 -->
        <div v-else-if="flatFindings.length" class="ai-result-findings">
          <div class="ai-result-findings-head">
            <span>审查发现</span>
            <small>{{ flatFindings.length }} 条 · 均需人工确认</small>
          </div>
          <article
            v-for="(finding, findingIndex) in flatFindings"
            :key="finding.id"
            :class="['ai-finding', `is-${finding.severityTone}`]"
          >
            <div class="ai-finding-head">
              <span class="ai-finding-index">{{ findingIndex + 1 }}</span>
              <h3>{{ finding.title || '审查发现' }}</h3>
              <AuditStatusTag v-if="finding.severityTag" :tone="finding.severityTone" round>
                {{ finding.severityTag }}
              </AuditStatusTag>
            </div>
            <p class="ai-finding-description">{{ finding.description }}</p>
          </article>
        </div>
      </article>

      <section class="ai-history" aria-label="历史 AI 复核结果">
        <div class="ai-history-head">
          <div>
            <h3>历史 AI 复核结果</h3>
            <p>按复核时间倒序排列</p>
          </div>
          <span>{{ history.length }} 次</span>
        </div>
        <div v-if="history.length" class="ai-history-list ai-history-timeline">
          <article v-for="item in history" :key="item.runId" class="ai-history-item">
            <div class="ai-history-item-head">
              <div>
                <strong>{{ item.sourceLabel }}</strong>
                <small>{{ item.meta || item.activityAt }}</small>
              </div>
              <AuditStatusTag :tone="item.statusTone" round>
                {{ item.resultLabel }}
              </AuditStatusTag>
            </div>
            <p>{{ item.summary }}</p>
          </article>
        </div>
        <p v-else class="ai-history-empty">暂无更早的 AI 复核结果</p>
      </section>
    </div>
  </section>
</template>

<style scoped>
.workbench-ai-review-panel {
  overflow: hidden;
  border-color: var(--aicheck-border-soft, #e5ecf6);
  border-radius: 12px;
  scroll-margin-top: 190px;
}

.ai-panel-head,
.ai-current-result-head,
.ai-history-head,
.ai-history-item-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.ai-panel-head {
  min-height: 62px;
  padding: 14px 20px;
  background: linear-gradient(105deg, #f8fbff 0%, #f3f7fd 100%);
}

.ai-panel-head h2 {
  margin: 0;
  font-size: 18px;
  line-height: 26px;
  color: var(--aicheck-text-strong, #172033);
}

.ai-panel-head .sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--aicheck-text-muted, #52647d);
}

.ai-run-meta {
  display: flex;
  max-width: 52%;
  gap: 6px;
  align-items: flex-end;
  flex-direction: column;
}

.ai-run-meta small,
.ai-history-item small,
.ai-history-head p {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-panel-body {
  display: grid;
  padding: 18px 20px 20px;
  gap: 14px;
}

.ai-status-banner {
  display: grid;
  min-height: 58px;
  padding: 11px 14px;
  color: var(--aicheck-danger, #b42318);
  background: linear-gradient(100deg, #fff5f4 0%, #fffafa 100%);
  border: 1px solid #f2d2cf;
  border-radius: 10px;
  box-shadow: inset 3px 0 0 var(--aicheck-danger, #b42318);
  grid-template-columns: 30px minmax(0, 1fr);
  align-items: start;
  gap: 10px;
}

.ai-status-banner__icon {
  display: grid;
  width: 28px;
  height: 28px;
  margin-top: 1px;
  font-size: 18px;
  color: #fff;
  background: var(--aicheck-danger, #b42318);
  border-radius: 50%;
  place-items: center;
}

.ai-status-banner__content {
  min-width: 0;
}

.ai-status-banner__content strong {
  display: block;
  font-size: 14px;
  line-height: 22px;
}

.ai-error-message {
  margin: 2px 0 0;
  font-size: 13px;
  line-height: 20px;
  color: #8f352e;
}

.ai-current-result {
  --ai-result-accent: var(--aicheck-primary, #1f66d8);

  padding: 20px;
  background: linear-gradient(135deg, #f7faff 0%, #fff 58%);
  border: 1px solid #dbe6f4;
  border-radius: 12px;
  box-shadow: 0 6px 18px rgb(31 72 125 / 6%);
}

.ai-current-result.is-red {
  --ai-result-accent: var(--aicheck-danger, #b42318);

  background: linear-gradient(135deg, #fff9f8 0%, #fff 58%);
  border-color: #ecd9d7;
}

.ai-current-result.is-orange {
  --ai-result-accent: var(--aicheck-warning, #b45309);

  background: linear-gradient(135deg, #fffaf2 0%, #fff 58%);
  border-color: #eee0c8;
}

.ai-current-result.is-green {
  --ai-result-accent: var(--aicheck-success, #16803c);

  background: linear-gradient(135deg, #f6fcf8 0%, #fff 58%);
  border-color: #d9eade;
}

.ai-current-result.is-gray {
  --ai-result-accent: var(--aicheck-text-subtle, #667085);

  background: linear-gradient(135deg, #f8fafc 0%, #fff 58%);
}

.ai-current-result-head > div,
.ai-history-item-head > div {
  display: grid;
  gap: 3px;
}

.ai-current-result-head span {
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-current-result-head strong {
  font-size: 16px;
  line-height: 24px;
  color: var(--aicheck-text-strong, #172033);
}

.ai-conclusion {
  /* 结论卡 */

  --ai-conclusion-accent: #667085;

  display: grid;
  padding: 14px 16px;
  margin-top: 14px;
  background: #fff;
  border: 0;
  border-radius: 10px;
  gap: 10px;
}

.ai-conclusion.is-red {
  --ai-conclusion-accent: var(--aicheck-danger, #b42318);
}

.ai-conclusion.is-orange {
  --ai-conclusion-accent: var(--aicheck-warning, #b45309);
}

.ai-conclusion.is-green {
  --ai-conclusion-accent: var(--aicheck-success, #16803c);
}

.ai-conclusion-head {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.ai-conclusion-headline {
  flex: 1 1 260px;
  min-width: 0;
  font-size: 15px;
  line-height: 22px;
  color: var(--aicheck-text-strong, #172033);
  overflow-wrap: anywhere;
}

.ai-conclusion-note {
  padding: 2px 8px;
  font-size: 12px;
  color: #7a4b00;
  background: #fff5e0;
  border: 1px solid #f3dfb0;
  border-radius: 999px;
}

.ai-conclusion-note.is-partial {
  color: var(--aicheck-danger, #b42318);
  background: #fff5f4;
  border-color: #f2d2cf;
}

/* 四格一行：原来是三列，加了「通过」之后第四格掉到下一行，读起来像两组数。 */
.ai-conclusion-counts {
  display: grid;
  margin: 0;
  gap: 8px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

@media (max-width: 720px) {
  .ai-conclusion-counts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.ai-conclusion-counts > div {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 6px 10px;
  background: #f8fafc;
  border-radius: 8px;
}

.ai-conclusion-counts dt {
  font-size: 12px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-conclusion-counts dd {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 24px;
}

.ai-conclusion-counts > .is-red dd {
  color: var(--aicheck-danger, #b42318);
}

.ai-conclusion-counts > .is-orange dd {
  color: var(--aicheck-warning, #b45309);
}

.ai-conclusion-counts > .is-green dd {
  color: #1a7f4b;
}

.ai-conclusion-counts > .is-blue dd {
  color: #2f6bff;
}

.ai-conclusion-counts > .is-gray dd {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-conclusion-facts {
  display: grid;
  padding: 0;
  margin: 0;
  list-style: none;
  gap: 4px;
}

.ai-conclusion-facts li {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
  font-size: 13px;
  line-height: 20px;
  color: #27364b;
}

.ai-conclusion-facts li > span {
  flex: 1 1 240px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.ai-conclusion-facts li::before {
  color: var(--ai-conclusion-accent);
  content: '•';
}

.ai-conclusion-facts small {
  color: var(--aicheck-text-subtle, #667085);
  overflow-wrap: anywhere;
}

.ai-conclusion-action {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 13px;
}

.ai-conclusion-action > span {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-conclusion-action > strong {
  color: var(--aicheck-text-strong, #172033);
}

.ai-conclusion-action > small {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-conclusion-supplement {
  margin-left: auto;
}

.ai-check-outcomes {
  display: grid;
  padding: 12px 0 0;
  margin-top: 14px;
  border-top: 1px solid #e6edf7;
  gap: 8px;
}

.ai-check-outcomes-head {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
  font-size: 13px;
}

.ai-check-outcomes-head strong {
  font-size: 14px;
  color: var(--aicheck-text-strong, #172033);
}

.ai-check-outcomes-head span,
.ai-check-outcomes-head small {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-check-outcomes ul {
  display: grid;
  padding: 0;
  margin: 0;
  list-style: none;
  gap: 6px;
}

.ai-check-outcomes li {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
  font-size: 13px;
  line-height: 20px;
  color: #27364b;
}

.ai-check-outcomes li > span {
  flex: 1 1 240px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.ai-check-outcomes li > small {
  color: var(--aicheck-text-subtle, #667085);
  font-variant-numeric: tabular-nums;
}

.ai-outcome-basis {
  display: grid;
  flex-basis: 100%;
  padding: 2px 0 0 22px;
  gap: 4px;
  font-size: 12px;
  line-height: 18px;
}

.ai-outcome-reason {
  margin: 0;
  color: #27364b;
}

.ai-outcome-reason > span {
  margin-right: 6px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-outcome-checks,
.ai-outcome-facts,
.ai-quote-source {
  padding: 0;
  border: none;
  background: none;
  color: var(--el-color-primary, #2f6bff);
  cursor: pointer;
  font-size: 12px;
  line-height: 18px;
}

.ai-quote-source:hover {
  text-decoration: underline;
}

.ai-outcome-quotes {
  display: grid;
  padding: 0;
  margin: 0;
  list-style: none;
  gap: 2px;
}

.ai-outcome-checks li {
  display: flex;
  gap: 6px;
  align-items: baseline;
  flex-wrap: wrap;
  font-size: 12px;
  line-height: 18px;
}

.ai-check-mark {
  width: 14px;
  font-style: normal;
  font-weight: 600;
  text-align: center;
}

.ai-check-mark.is-pass {
  color: #1a7f4b;
}

.ai-check-mark.is-fail {
  color: #b42318;
}

.ai-outcome-checks small,
.ai-outcome-quotes small {
  color: var(--aicheck-text-subtle, #667085);
  font-variant-numeric: tabular-nums;
}

.ai-outcome-fact-head {
  display: flex;
  gap: 8px;
  align-items: baseline;
  flex-wrap: wrap;
}

.ai-fact-unscored {
  color: #b54708;
}

.ai-fact-unidentified {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 18px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-fact-unidentified button {
  padding: 0 0 0 6px;
  border: none;
  background: none;
  color: var(--el-color-primary, #2f6bff);
  cursor: pointer;
  font-size: 12px;
}

.ai-fact-unidentified button:hover {
  text-decoration: underline;
}

.ai-fact-group-head {
  display: flex;
  gap: 8px;
  align-items: baseline;
  margin-top: 8px;
  font-size: 12px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-fact-group-head strong {
  color: #27364b;
}

.ai-fact-more button {
  padding: 0;
  border: none;
  background: none;
  color: var(--el-color-primary, #2f6bff);
  cursor: pointer;
  font-size: 12px;
}

.ai-fact-more button:hover {
  text-decoration: underline;
}

.ai-clause-list {
  display: grid;
  padding: 8px 0 0;
  margin: 0;
  list-style: none;
  gap: 6px;
}

.ai-clause-list li {
  padding-left: 10px;
  border-left: 3px solid #d8e3f8;
}

.ai-clause-kind {
  padding: 0 6px;
  border-radius: 3px;
  background: #eef2f8;
  color: #5a6b85;
  font-size: 11px;
  font-style: normal;
  line-height: 18px;
  white-space: nowrap;
}

/* 资料原文不是规范要求，用中性偏暖的底色和标准条款区分开 */
.ai-clause-kind.is-document {
  background: #fdf3e7;
  color: #96601f;
}

.ai-clause-kind.is-unregistered_standard {
  background: #f3eefc;
  color: #6b4fa8;
}

.ai-clause-head {
  display: flex;
  gap: 8px;
  align-items: baseline;
  flex-wrap: wrap;
  font-size: 12px;
  line-height: 18px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-clause-head strong {
  color: #27364b;
}

.ai-clause-superseded {
  padding: 0 6px;
  border-radius: 999px;
  background: #fdeceb;
  color: #b42318;
  font-weight: 600;
}

.ai-clause-list q {
  display: block;
  margin-top: 2px;
  quotes: '「' '」';
  font-size: 12px;
  line-height: 19px;
  color: #27364b;
  overflow-wrap: anywhere;
}

.ai-stale-notice {
  margin: 0 0 10px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #fff8ec;
  color: #b54708;
  font-size: 12px;
  line-height: 18px;
}

.ai-fact-same-count {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-fact-platform {
  padding: 0 6px;
  border-radius: 999px;
  background: #e8f5ee;
  color: #1a7f4b;
}

.ai-outcome-facts > li.is-platform-verified {
  padding: 4px 8px;
  margin-left: -8px;
  border-radius: 6px;
  background: #f4fbf7;
}

.ai-fact-confirmed {
  color: #1a7f4b;
}

/* 期望/实际换行时靠右，别贴到行首去 */
.ai-outcome-checks li small {
  margin-left: auto;
  text-align: right;
}

.ai-outcome-quotes {
  padding-left: 12px;
  border-left: 2px solid #e6edf7;
}

.ai-outcome-quotes li {
  display: flex;
  gap: 8px;
  align-items: baseline;
  flex-wrap: wrap;
  font-size: 12px;
  line-height: 18px;
}

.ai-outcome-quotes q {
  quotes: '「' '」';
  overflow-wrap: anywhere;
  color: #27364b;
}

.ai-outcome-facts-block {
  display: grid;
  padding-top: 10px;
  margin-top: 6px;
  border-top: 1px dashed #e6edf7;
  gap: 6px;
}

.ai-outcome-facts-block .ai-outcome-facts {
  gap: 8px;
}

.ai-outcome-facts-block .ai-outcome-quotes q {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.ai-unscored-fact-label {
  color: var(--aicheck-text-subtle, #667085);
}

.ai-unscored-fact-value {
  font-variant-numeric: tabular-nums;
}

.ai-result-summary {
  max-width: 960px;
  margin: 13px 0 0;
  font-size: 14px;
  line-height: 1.75;
  color: #27364b;
}

.ai-result-findings {
  /* 发现分组 */

  display: grid;
  margin-top: 16px;
  gap: 10px;
}

.ai-result-findings-head {
  display: flex;
  gap: 10px;
  align-items: center;
  padding-top: 14px;
  border-top: 1px solid #e3ebf5;
}

.ai-result-findings-head > span {
  font-size: 13px;
  font-weight: 600;
  color: var(--aicheck-text-strong, #172033);
}

.ai-result-findings-head > small {
  font-size: 12px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-insufficient-toggle {
  width: 100%;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border-right: 0;
  border-bottom: 0;
  border-left: 0;
}

.ai-insufficient-caret {
  margin-left: auto;
  font-size: 12px;
  color: var(--aicheck-primary, #1f66d8);
}

.ai-claim-list {
  display: grid;
  padding: 10px 12px;
  margin: 0;
  list-style: none;
  background: #f8fafc;
  border: 1px dashed #d5dfeb;
  border-radius: 8px;
  gap: 6px;
}

.ai-claim-list li {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 13px;
  line-height: 20px;
  color: #34445a;
}

.ai-claim-list li > span:first-child {
  flex: 1 1 auto;
  min-width: 0;
}

.ai-finding {
  --ai-finding-accent: #9db5d3;

  padding: 14px 16px;
  background: #fff;
  border: 1px solid #e3ebf5;
  border-radius: 10px;
}

.ai-finding.is-blue {
  --ai-finding-accent: var(--aicheck-primary, #1f66d8);
}

.ai-finding.is-orange {
  --ai-finding-accent: var(--aicheck-warning, #b45309);
}

.ai-finding.is-red {
  --ai-finding-accent: var(--aicheck-danger, #b42318);
}

.ai-finding.is-gray {
  background: #fbfcfe;
}

.ai-finding-head {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.ai-finding-head h3 {
  flex: 1 1 240px;
  min-width: 0;
  margin: 0;
  font-size: 15px;
  line-height: 22px;
  color: var(--aicheck-text-strong, #172033);
}

.ai-finding-index {
  display: inline-grid;
  width: 22px;
  height: 22px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: var(--ai-finding-accent);
  border-radius: 50%;
  place-items: center;
}

.ai-finding-confidence {
  font-size: 12px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-finding-decision {
  padding: 1px 8px;
  font-size: 12px;
  color: #0f5132;
  background: #e6f4ea;
  border-radius: 999px;
}

.ai-finding-chips {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.ai-chip {
  padding: 2px 8px;
  font-size: 12px;
  line-height: 18px;
  color: #52647a;
  background: #edf2f8;
  border-radius: 999px;
}

.ai-chip.is-action {
  color: #1f4f9a;
  background: #e6efff;
}

.ai-chip.is-policy {
  color: #1f4f9a;
  background: #e6efff;
  border: 1px dashed #9fbdf0;
}

.ai-chip.is-unverified {
  color: #7a4b00;
  background: #fff5e0;
}

.ai-finding-description {
  margin: 8px 0 0;
  font-size: 13.5px;
  line-height: 1.75;
  color: #34445a;
}

.ai-finding-description.is-clamped {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-clamp: 3;
}

.ai-link-button {
  padding: 0;
  margin-top: 4px;
  font-size: 12px;
  color: var(--aicheck-primary, #1f66d8);
  cursor: pointer;
  background: transparent;
  border: 0;
}

.ai-model-text {
  padding: 10px 12px;
  margin: 8px 0 0;
  background: #fffaf0;
  border: 1px dashed #e8d3a3;
  border-radius: 8px;
}

.ai-model-text p {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: #5c4a1f;
  user-select: none;
}

.ai-finding-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.ai-evidence-groups {
  display: grid;
  margin-top: 12px;
  gap: 8px;
}

.ai-evidence-group {
  padding: 8px 10px;
  background: #f6f9fd;
  border: 1px dashed #d5e1f0;
  border-radius: 8px;
}

.ai-evidence-file {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  max-width: 100%;
  padding: 0;
  font-size: 13px;
  color: var(--aicheck-primary, #1f66d8);
  cursor: pointer;
  background: transparent;
  border: 0;
}

.ai-evidence-file:hover .ai-evidence-file-name {
  text-decoration: underline;
}

.ai-evidence-file-icon {
  font-size: 12px;
  opacity: 0.7;
}

.ai-evidence-file-name {
  overflow: hidden;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ai-evidence-file small {
  font-size: 12px;
  color: var(--aicheck-text-subtle, #667085);
}

.ai-evidence-quotes {
  display: flex;
  gap: 6px;
  padding: 0;
  margin: 6px 0 0;
  list-style: none;
  flex-wrap: wrap;
}

.ai-evidence-quotes li {
  max-width: 100%;
  padding: 2px 8px;
  overflow: hidden;
  font-size: 12px;
  line-height: 20px;
  color: #3f5068;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: #fff;
  border: 1px solid #dfe8f3;
  border-radius: 999px;
}

.ai-evidence-quotes li::before {
  color: #9db5d3;
  content: '“';
}

.ai-evidence-quotes li::after {
  color: #9db5d3;
  content: '”';
}

.ai-rule-list {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.ai-rule-list span {
  padding: 3px 8px;
  font-size: 12px;
  color: #52647a;
  background: #edf2f8;
  border-radius: 999px;
}

.ai-history {
  padding: 17px 4px 0;
  margin-top: 2px;
  border-top: 1px solid var(--aicheck-border-soft, #e5ecf6);
}

.ai-history-head h3,
.ai-history-head p,
.ai-history-item p {
  margin: 0;
}

.ai-history-head h3 {
  font-size: 14px;
  font-weight: 600;
  line-height: 22px;
  color: var(--aicheck-text-strong, #172033);
}

.ai-history-head p {
  margin-top: 2px;
  font-size: 12px;
}

.ai-history-head > span {
  padding: 2px 8px;
  font-size: 12px;
  color: #52647a;
  background: #f0f4f9;
  border-radius: 999px;
}

.ai-history-list {
  display: grid;
  margin: 10px 0 0 5px;
}

.ai-history-timeline {
  padding-left: 16px;
  border-left: 1px solid #dce5f0;
}

.ai-history-item {
  position: relative;
  padding: 13px 10px 14px 2px;
  background: transparent;
  border-bottom: 1px solid #e8eef5;
}

.ai-history-item::before {
  position: absolute;
  top: 20px;
  left: -21px;
  width: 9px;
  height: 9px;
  background: #fff;
  border: 2px solid #9db5d3;
  border-radius: 50%;
  content: '';
}

.ai-history-item:last-child {
  padding-bottom: 4px;
  border-bottom: 0;
}

.ai-history-item p {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: #48566a;
}

.ai-history-item small {
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ai-history-empty {
  padding: 15px;
  margin: 10px 0 0;
  color: var(--aicheck-text-subtle, #667085);
  text-align: center;
  background: #f8fafc;
  border-radius: 10px;
}

@media (width <= 720px) {
  .ai-panel-head,
  .ai-current-result-head,
  .ai-history-item-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .ai-run-meta {
    max-width: 100%;
    align-items: flex-start;
  }

  .ai-run-meta small {
    overflow-wrap: anywhere;
  }

  .ai-panel-body {
    padding: 14px;
  }

  .ai-current-result {
    padding: 16px;
  }

  .ai-conclusion-counts {
    grid-template-columns: 1fr;
  }

  .ai-history-item-head {
    gap: 8px;
  }
}
</style>
