<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElAlert, ElButton, ElCard, ElDialog, ElInput, ElPagination, ElTable, ElTableColumn } from 'element-plus'
import request from '@/axios'

type RequestRecord = { id: string; requestText: string; platform: string; nodeIds: number[]; createdAt: string }
const rows = ref<RequestRecord[]>([])
const keyword = ref('')
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const error = ref('')
const selected = ref<RequestRecord>()
const visible = ref(false)
let generation = 0
async function load(reset = false) {
  if (reset) page.value = 1
  const current = ++generation
  loading.value = true
  error.value = ''
  try {
    const response = await request.get({ url: '/api/inspection-services/requests', params: { keyword: keyword.value, page: page.value, pageSize: 20 } })
    if (current !== generation) return
    rows.value = response.data.items
    total.value = response.data.total
  } catch {
    if (current === generation) { error.value = '请求记录加载失败，请重试。'; rows.value = []; total.value = 0 }
  } finally {
    if (current === generation) loading.value = false
  }
}
function show(row: RequestRecord) { selected.value = row; visible.value = true }
onMounted(() => load())
</script>

<template>
  <ElCard shadow="never">
    <template #header>Skill 请求记录</template>
    <p class="note">保存用户本次审查请求，不含附件或审查报告。平台名称由调用方填写，未核实提交者身份。</p>
    <div class="toolbar">
      <ElInput v-model="keyword" placeholder="搜索请求文本或平台" clearable maxlength="200" @keyup.enter="load(true)" />
      <ElButton type="primary" :loading="loading" @click="load(true)">查询</ElButton>
      <ElButton :disabled="loading" @click="load()">刷新</ElButton>
    </div>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <ElTable v-loading="loading" :data="rows" empty-text="暂无请求记录">
      <ElTableColumn label="提交时间" width="190"><template #default="{ row }">{{ new Date(row.createdAt).toLocaleString() }}</template></ElTableColumn>
      <ElTableColumn prop="platform" label="平台" width="130" />
      <ElTableColumn prop="requestText" label="请求文本" min-width="300" show-overflow-tooltip />
      <ElTableColumn label="节点" width="180"><template #default="{ row }">{{ row.nodeIds.map((n: number) => `R${String(n).padStart(2, '0')}`).join('、') || '未指定' }}</template></ElTableColumn>
      <ElTableColumn label="操作" width="100"><template #default="{ row }"><ElButton link type="primary" @click="show(row)">查看全文</ElButton></template></ElTableColumn>
    </ElTable>
    <ElPagination v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="load()" />
    <ElDialog v-model="visible" title="请求全文" width="min(760px, 92vw)">
      <p v-if="selected" class="note">记录编号：{{ selected.id }}</p>
      <pre class="request-text">{{ selected?.requestText }}</pre>
    </ElDialog>
  </ElCard>
</template>

<style scoped>
.toolbar { display: flex; gap: 12px; margin: 16px 0; }
.toolbar .el-input { max-width: 480px; }
.note { color: var(--el-text-color-secondary); font-size: 13px; }
.request-text { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.8; }
.el-pagination { margin-top: 16px; }
</style>
