<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElButton, ElDrawer, ElEmpty, ElMessage, ElTable, ElTableColumn, ElTag } from 'element-plus'
import {
  exportFdeRawVaultApi,
  getFdeRawVaultApi,
  getFdeRawVaultPayloadApi,
  verifyFdeRawVaultApi
} from '@/api/aicheck'
import type { FdeRawVaultEvent, FdeRawVaultSummary } from '@/api/aicheck'

const props = defineProps<{ reviewRunId: string }>()
const loading = ref(false)
const actionLoading = ref(false)
const summary = ref<FdeRawVaultSummary | null>(null)
const payloadVisible = ref(false)
const payloadTitle = ref('')
const payloadText = ref('')

const statusText: Record<string, string> = {
  complete: '完整归档',
  archive_incomplete: '归档处理中',
  unrecoverable_gap: '存在不可恢复缺口',
  hash_mismatch: '完整性校验失败',
  legacy_not_captured: '历史运行未采集'
}

const load = async () => {
  if (!props.reviewRunId) return
  loading.value = true
  try {
    summary.value = (await getFdeRawVaultApi(props.reviewRunId)).data
  } finally {
    loading.value = false
  }
}

const openPayload = async (event: FdeRawVaultEvent) => {
  if (!event.hasPayload) return
  actionLoading.value = true
  try {
    const response = await getFdeRawVaultPayloadApi(event.id)
    payloadText.value = await response.data.text()
    payloadTitle.value = `${event.sequence}. ${event.eventType}`
    payloadVisible.value = true
  } finally {
    actionLoading.value = false
  }
}

const verify = async () => {
  actionLoading.value = true
  try {
    const result = (await verifyFdeRawVaultApi(props.reviewRunId)).data
    ElMessage[result.status === 'verified' ? 'success' : 'error'](
      result.status === 'verified' ? '原始档案哈希链校验通过' : '原始档案完整性校验失败'
    )
    await load()
  } finally {
    actionLoading.value = false
  }
}

const exportArchive = async () => {
  actionLoading.value = true
  try {
    const response = await exportFdeRawVaultApi(props.reviewRunId)
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${props.reviewRunId}-raw-vault.zip`
    anchor.click()
    URL.revokeObjectURL(url)
  } finally {
    actionLoading.value = false
  }
}

onMounted(load)
watch(() => props.reviewRunId, load)
</script>

<template>
  <section class="raw-vault-panel" data-testid="fde-raw-vault-panel">
    <div class="raw-vault-toolbar">
      <div>
        <strong>Agent 原始运行档案</strong>
        <small>逐字节保存模型交换、Agent 轮次及工具调用，可离线校验。</small>
      </div>
      <div>
        <ElButton :loading="actionLoading" @click="verify">校验完整性</ElButton>
        <ElButton type="primary" plain :loading="actionLoading" @click="exportArchive">
          导出原始档案
        </ElButton>
      </div>
    </div>
    <div v-if="summary" class="raw-vault-status">
      <ElTag
        :type="
          summary.status === 'complete'
            ? 'success'
            : summary.status === 'hash_mismatch'
              ? 'danger'
              : 'warning'
        "
      >
        {{ statusText[summary.status] || summary.status }}
      </ElTag>
      <span>事件 {{ summary.eventCount }}</span>
      <span>待归档 {{ summary.pendingCount }}</span>
      <span class="raw-vault-chain">链头 {{ summary.chainHead || '-' }}</span>
    </div>
    <ElTable
      v-if="summary?.events.length"
      v-loading="loading"
      :data="summary.events"
      border
      @row-click="openPayload"
    >
      <ElTableColumn prop="sequence" label="#" width="64" />
      <ElTableColumn prop="eventType" label="事件" min-width="210" />
      <ElTableColumn prop="turn" label="轮次" width="70" />
      <ElTableColumn prop="payloadByteLength" label="字节" width="90" />
      <ElTableColumn prop="payloadHash" label="载荷哈希" min-width="230" show-overflow-tooltip />
      <ElTableColumn label="原文" width="86">
        <template #default="{ row }">
          <ElButton v-if="row.hasPayload" link type="primary" :loading="actionLoading">
            查看
          </ElButton>
          <span v-else>-</span>
        </template>
      </ElTableColumn>
    </ElTable>
    <ElEmpty v-else-if="!loading" description="当前运行没有原始档案" />
    <ElDrawer v-model="payloadVisible" :title="payloadTitle" size="60%" append-to-body>
      <pre class="raw-vault-payload">{{ payloadText }}</pre>
    </ElDrawer>
  </section>
</template>

<style scoped>
.raw-vault-toolbar,
.raw-vault-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.raw-vault-toolbar small {
  display: block;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
}

.raw-vault-status {
  justify-content: flex-start;
  font-size: 13px;
}

.raw-vault-chain {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.raw-vault-payload {
  margin: 0;
  font:
    13px/1.6 ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
