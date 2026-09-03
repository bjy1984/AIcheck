<script setup lang="ts">
import { computed } from 'vue'
import AuditStatusTag from './AuditStatusTag.vue'
import type { WorkbenchCertificateVerification } from '../workbenchReviewPresentation'

// 证照/资格证的确定性核验结论。它不是模型说的，是服务端按有效期、持证主体、
// 许可范围算出来的；监检看这一块就能知道「证还有效吗」，不必在 finding 文字里翻。
const props = defineProps<{ verification: WorkbenchCertificateVerification }>()

const toneOf = (result: string): 'green' | 'red' | 'orange' | 'gray' =>
  result === 'passed' ? 'green' : result === 'failed' ? 'red' : result ? 'orange' : 'gray'
const labelOf = (result: string) =>
  result === 'passed'
    ? '核验通过'
    : result === 'failed'
      ? '核验未通过'
      : result === 'evidence_insufficient'
        ? '证据不足'
        : result || '未核验'

const overallTone = computed(() => toneOf(props.verification.result))
const overallLabel = computed(() => labelOf(props.verification.result))
const periodText = computed(() => {
  const period = props.verification.period
  if (period?.start || period?.end) return `${period.start || '?'} ～ ${period.end || '?'}`
  return `施工期未登记，按 ${period?.referenceDate || '当日'} 判断是否过期`
})
const warningText = (code: string) => {
  if (code === 'construction_period_missing_using_reference_date')
    return '项目未填施工起止，只能判断证书当前是否过期'
  if (code === 'no_certificate_extracted' || code === 'no_certificate_document_in_input')
    return '本节点资料里没有可核验的证书'
  if (code.startsWith('issuer_missing')) return `未识别到发证机关：${code.split(':')[1] || ''}`
  if (code.startsWith('valid_until_missing')) return `未识别到有效期：${code.split(':')[1] || ''}`
  if (code.startsWith('holder_missing')) return `未识别到持证主体：${code.split(':')[1] || ''}`
  if (code.startsWith('certificate_no_missing'))
    return `未识别到证书编号：${code.split(':')[1] || ''}`
  return code
}
</script>

<template>
  <section class="cert-verification" aria-label="证照核验结论">
    <div class="cert-verification-head">
      <div>
        <strong>证照核验</strong>
        <small>{{ verification.certificateType || '' }} · {{ periodText }}</small>
      </div>
      <AuditStatusTag :tone="overallTone" round>{{ overallLabel }}</AuditStatusTag>
    </div>
    <table v-if="verification.certificates.length" class="cert-verification-table">
      <thead>
        <tr>
          <th>持证主体</th>
          <th>证书编号</th>
          <th>有效期至</th>
          <th>范围 / 项目</th>
          <th>结论</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="cert in verification.certificates" :key="cert.certificateNo || cert.label">
          <td>{{ cert.holder || '-' }}</td>
          <td>{{ cert.certificateNo || '-' }}</td>
          <td>{{ cert.validUntil || '未识别' }}</td>
          <td>{{ (cert.scopes || []).join('、') || '-' }}</td>
          <td
            ><AuditStatusTag :tone="toneOf(cert.result)" round>{{
              labelOf(cert.result)
            }}</AuditStatusTag></td
          >
        </tr>
      </tbody>
    </table>
    <ul v-if="verification.warnings.length" class="cert-verification-warnings">
      <li v-for="code in verification.warnings" :key="code">{{ warningText(code) }}</li>
    </ul>
  </section>
</template>

<style scoped>
.cert-verification {
  margin: 12px 0;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}
.cert-verification-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.cert-verification-head small {
  display: block;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}
.cert-verification-table {
  width: 100%;
  margin-top: 10px;
  border-collapse: collapse;
  font-size: 13px;
}
.cert-verification-table th,
.cert-verification-table td {
  padding: 6px 8px;
  text-align: left;
  border-bottom: 1px solid var(--el-border-color-lighter);
  vertical-align: top;
}
.cert-verification-table th {
  color: var(--el-text-color-secondary);
  font-weight: 500;
}
.cert-verification-warnings {
  margin: 8px 0 0;
  padding-left: 18px;
  color: var(--el-color-warning-dark-2);
  font-size: 12px;
}
</style>
