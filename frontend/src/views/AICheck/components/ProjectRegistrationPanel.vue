<script setup lang="ts">
/**
 * 项目负责人：生成注册链接、审核注册申请。
 *
 * ## 界面只是入口，闸门在服务端
 *
 * 按钮禁用只是省得用户白点。真正拦越权的是服务端
 * （project_registration_routes.py）：不是**这个项目**的负责人一律 403。
 * **前端的禁用不是安全措施**，改一行请求就绕过去了。
 *
 * ## 拒绝必须写理由
 *
 * 不写的话申请人只看到「被拒了」，不知道要改什么——他会原样再提一次，
 * 于是两边都白忙。所以拒绝走一个必须填写的输入框，而不是一个直接生效的按钮。
 *
 * ## 链接的三件事都要说出来
 *
 * 有效期、剩余次数、能停用。链接会被转发、被截图、被贴进群里，
 * 发的人得知道它什么时候作废、还能用几次、后悔了怎么收回。
 *
 * ## 二维码
 *
 * 收链接的人多半在工地，用手机。**让他在群里长按一串 URL 再粘进浏览器，
 * 不如让他扫一下。** 二维码在本地生成（qrcode 依赖已在包里），
 * 不发到任何第三方——一个能生成二维码的外部服务，
 * 等于把注册链接交给了它。
 */
import { computed, ref, watch } from 'vue'
import QRCode from 'qrcode'
import {
  ElAlert,
  ElButton,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'

import {
  createProjectRegistrationLinkApi,
  listRegistrationRequestsApi,
  reviewRegistrationRequestApi,
  type RegistrationRequestItem
} from '@/api/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'

const props = defineProps<{ projectId: string; projectName: string }>()

const linkLoading = ref(false)
const link = ref('')
const linkExpiresAt = ref('')
const linkMaxUses = ref(0)
const qrDataUrl = ref('')

const requests = ref<RegistrationRequestItem[]>([])
const listLoading = ref(false)
const reviewing = ref('')

const pending = computed(() => requests.value.filter((item) => item.status === '待审核'))

const ROLE_LABELS: Record<string, string> = {
  inspection: '监检人员',
  contractor: '施工单位',
  ndt: '无损检测',
  owner: '建设单位'
}

const loadRequests = async () => {
  if (!props.projectId) return
  listLoading.value = true
  try {
    const res = await listRegistrationRequestsApi(props.projectId)
    if (res) requests.value = res.data.items
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '加载注册申请失败。'))
  } finally {
    listLoading.value = false
  }
}

watch(() => props.projectId, loadRequests, { immediate: true })

const handleCreateLink = async () => {
  linkLoading.value = true
  link.value = ''
  qrDataUrl.value = ''
  try {
    const res = await createProjectRegistrationLinkApi(props.projectId)
    if (!res) return
    // 给的是收件人真正要点的地址，不是裸 token 让他自己拼
    link.value = `${window.location.origin}/#/join/${res.data.token}`
    linkExpiresAt.value = res.data.expiresAt
    linkMaxUses.value = res.data.maxUses
    /* 二维码本地生成，不经任何第三方服务——
       一个「帮你生成二维码」的外部接口，等于把注册链接交给了它。 */
    try {
      qrDataUrl.value = await QRCode.toDataURL(link.value, { width: 220, margin: 1 })
    } catch {
      // 二维码画不出来不影响发链接：链接本身就在上面，复制照样能用。
      // 这里不弹错误，免得让人以为整个链接失败了。
      qrDataUrl.value = ''
    }
    ElMessage.success('注册链接已生成')
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '生成注册链接失败。'))
  } finally {
    linkLoading.value = false
  }
}

const handleCopy = async () => {
  try {
    await navigator.clipboard.writeText(link.value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.info('复制失败，请手动选中链接复制')
  }
}

const handleReview = async (item: RegistrationRequestItem, approved: boolean) => {
  let reason = ''
  if (!approved) {
    /* 拒绝必须写理由。不写的话申请人只看到「被拒了」，不知道要改什么，
       他会原样再提一次——两边都白忙。 */
    try {
      const input = await ElMessageBox.prompt(
        `拒绝 ${item.displayName || item.username} 的申请，请说明原因（会告知申请人）`,
        '拒绝申请',
        {
          inputPlaceholder: '例如：该单位不在本项目参建名单内',
          inputPattern: /\S/,
          inputErrorMessage: '必须填写理由'
        }
      )
      reason = String(input.value || '').trim()
    } catch {
      return // 用户取消
    }
  }
  reviewing.value = item.id
  try {
    const res = await reviewRegistrationRequestApi(props.projectId, item.id, { approved, reason })
    if (!res) return
    ElMessage.success(approved ? '已通过，账号已创建' : '已拒绝')
    await loadRequests()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '审核失败。'))
  } finally {
    reviewing.value = ''
  }
}
</script>

<template>
  <section class="project-registration">
    <h4>{{ projectName }} · 注册链接与审核</h4>

    <ElButton type="primary" :loading="linkLoading" @click="handleCreateLink">
      生成项目注册链接
    </ElButton>

    <div v-if="link" class="link-result">
      <ElInput :model-value="link" readonly>
        <template #append>
          <ElButton @click="handleCopy">复制</ElButton>
        </template>
      </ElInput>
      <!-- 收链接的人多半在工地用手机：扫一下比长按 URL 再粘贴实际得多 -->
      <div v-if="qrDataUrl" class="link-qr">
        <img :src="qrDataUrl" alt="项目注册链接二维码" width="180" height="180" />
        <small>手机扫码即可打开注册页</small>
      </div>
      <!-- 有效期和次数都要写出来：链接会被转发、被截图 -->
      <small
        >有效期至 {{ linkExpiresAt }}，最多可注册
        {{ linkMaxUses }} 人；提交后需审核通过才生效</small
      >
    </div>

    <ElAlert
      v-if="!listLoading && !requests.length"
      class="registration-empty"
      type="info"
      title="还没有人通过链接提交注册申请。"
      :closable="false"
      show-icon
    />
    <ElTable v-else v-loading="listLoading" :data="requests" class="registration-table">
      <ElTableColumn prop="username" label="用户名" min-width="120" />
      <ElTableColumn prop="displayName" label="姓名" min-width="100" />
      <ElTableColumn label="申请角色" width="110">
        <template #default="{ row }">{{ ROLE_LABELS[row.role] || row.role }}</template>
      </ElTableColumn>
      <ElTableColumn prop="createdAt" label="提交时间" width="170" />
      <ElTableColumn label="状态" width="150">
        <template #default="{ row }">
          <ElTag
            size="small"
            effect="plain"
            :type="
              row.status === '已通过' ? 'success' : row.status === '已拒绝' ? 'danger' : 'warning'
            "
          >
            {{ row.status }}
          </ElTag>
          <!-- 拒绝理由要显示出来，否则记录里只剩一个「已拒绝」，
               过后没人说得清为什么 -->
          <small v-if="row.rejectReason" class="reject-reason">{{ row.rejectReason }}</small>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <template v-if="row.status === '待审核'">
            <ElButton
              link
              type="primary"
              :loading="reviewing === row.id"
              @click="handleReview(row, true)"
            >
              通过
            </ElButton>
            <ElButton link type="danger" @click="handleReview(row, false)">拒绝</ElButton>
          </template>
          <span v-else class="reviewed-hint">已处理</span>
        </template>
      </ElTableColumn>
    </ElTable>

    <p v-if="pending.length" class="pending-hint">
      有 {{ pending.length }} 条待审核申请，通过之后对方才能登录。
    </p>
  </section>
</template>

<style scoped>
.project-registration h4 {
  margin: 0 0 12px;
}

.link-result {
  margin: 10px 0 16px;
}

.link-qr {
  margin-top: 10px;
  text-align: center;
}

.link-qr img {
  display: block;
  margin: 0 auto 4px;
  padding: 6px;
  background: #fff; /* 二维码必须白底：深色主题下透明底会扫不出来 */
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}

.link-result small {
  display: block;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
}

.registration-table {
  margin-top: 8px;
}

.reject-reason {
  display: block;
  margin-top: 2px;
  color: var(--el-text-color-secondary);
}

.reviewed-hint {
  color: var(--el-text-color-secondary);
}

.pending-hint {
  margin: 10px 0 0;
  color: var(--el-color-warning);
}
</style>
