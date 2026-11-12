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
 *
 * ## 单位由申请人填，审核人可改（2026-11-11 客户反馈）
 *
 * 不用先去「组织用户」建组织：通过时没有这个单位就自动建。
 * 申请单位和项目已有单位名字不同时**不自动合并**（资料按单位隔离，
 * 合错了两家会互相看到资料），弹窗让审核人选「并入已有单位」还是「算作新单位」。
 *
 * ## 打开就有链接
 *
 * 客户建完项目找不到怎么分享：面板打开时直接生成好链接和二维码，
 * 不用再找「生成」按钮。
 */
import { computed, onMounted, ref, watch } from 'vue'
import QRCode from 'qrcode'
import {
  ElAlert,
  ElButton,
  ElDialog,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'

import {
  createProjectRegistrationLinkApi,
  listProjectMemberAccountsApi,
  listRegistrationRequestsApi,
  resetProjectMemberPasswordApi,
  reviewRegistrationRequestApi,
  type ProjectMemberAccount,
  type RegistrationRequestItem
} from '@/api/aicheck'
import { getAicheckErrorMessage, getLatestAicheckBusinessError } from '@/utils/aicheckError'

const props = withDefaults(
  defineProps<{ projectId: string; projectName: string; autoCreateLink?: boolean }>(),
  { autoCreateLink: true }
)
const emit = defineEmits<{ (e: 'pending-change', count: number): void }>()

const linkLoading = ref(false)
const link = ref('')
const linkExpiresAt = ref('')
const linkMaxUses = ref(0)
const qrDataUrl = ref('')

const requests = ref<RegistrationRequestItem[]>([])
const listLoading = ref(false)
const reviewing = ref('')

/* 有效期按本地时间写到分钟：原样显示服务端的 2026-11-19T07:26:44.376954+00:00 没人看得懂 */
const formatExpiry = (value: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

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
    if (res) {
      requests.value = res.data.items
      emit('pending-change', res.data.pendingCount ?? pending.value.length)
    }
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '加载注册申请失败。'))
  } finally {
    listLoading.value = false
  }
}

/* 已加入的施工方、无损、建设方成员。忘了密码的人原来只能找特检院系统管理员，
   客户说他们根本不知道管理员是谁；邀请他们的负责人在这里就能替他重置（2026-11-12）。 */
const members = ref<ProjectMemberAccount[]>([])
const membersLoading = ref(false)
const resetting = ref('')
const resetResult = ref<{ name: string; username: string; password: string }>()

const loadMembers = async () => {
  if (!props.projectId) return
  membersLoading.value = true
  try {
    const res = await listProjectMemberAccountsApi(props.projectId)
    if (res) members.value = res.data.items
  } catch {
    members.value = []
  } finally {
    membersLoading.value = false
  }
}

const handleResetPassword = async (member: ProjectMemberAccount) => {
  const who = member.name || member.username
  try {
    await ElMessageBox.confirm(
      `给「${who}」生成一个临时密码。对方原来的密码马上失效，已登录的手机或电脑会被退出；用临时密码登录后要改成自己的密码。`,
      '重置密码',
      { confirmButtonText: '生成临时密码', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  resetting.value = member.userId
  try {
    const res = await resetProjectMemberPasswordApi(props.projectId, member.userId)
    if (!res) {
      ElMessage.error(getLatestAicheckBusinessError()?.message || '重置失败，请稍后再试。')
      return
    }
    resetResult.value = {
      name: who,
      username: res.data.username,
      password: res.data.temporaryPassword
    }
    void loadMembers()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '重置失败，请稍后再试。'))
  } finally {
    resetting.value = ''
  }
}

const copyResetMessage = async () => {
  if (!resetResult.value) return
  const { username, password } = resetResult.value
  const text = `账号：${username}\n临时密码：${password}\n登录后系统会让你改成自己的密码。`
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制，可以发给对方')
  } catch {
    ElMessage.warning('复制失败，请手动抄下临时密码')
  }
}

watch(() => props.projectId, loadRequests, { immediate: true })
watch(() => props.projectId, loadMembers, { immediate: true })

onMounted(() => {
  if (props.autoCreateLink && props.projectId) void handleCreateLink(true)
})

const handleCreateLink = async (silent = false) => {
  linkLoading.value = true
  link.value = ''
  qrDataUrl.value = ''
  try {
    // 打开面板时沿用还有效的链接；点「重新生成」才发新的
    const res = await createProjectRegistrationLinkApi(props.projectId, { reuse: silent })
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
    if (!silent) ElMessage.success('已生成新的邀请链接')
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '生成邀请链接失败。'))
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

const orgOf = (item: RegistrationRequestItem) => item.approvedOrgName || item.orgName || ''

const orgDiffers = (item: RegistrationRequestItem) => {
  const mine = normalizeOrg(item.orgName)
  const project = normalizeOrg(item.projectOrgName)
  return Boolean(mine && project && mine !== project)
}

function normalizeOrg(value?: string) {
  return String(value || '')
    .normalize('NFKC')
    .replace(/\s+/g, '')
    .toLowerCase()
}

const errorData = (error: unknown) => {
  const fromResponse = (error as { response?: { data?: { data?: unknown } } })?.response?.data
    ?.data as Record<string, unknown> | undefined
  return fromResponse || (getLatestAicheckBusinessError()?.data as Record<string, unknown>)
}

/* 通过前先确认单位：申请人填的可能是简称、错字，审核人当场改。 */
const askOrgName = async (item: RegistrationRequestItem) => {
  try {
    const input = await ElMessageBox.prompt(
      `通过 ${item.displayName || item.username}（${ROLE_LABELS[item.role] || item.role}）的申请。` +
        '请确认所属单位，需要时可修改；系统里没有这个单位会自动新建。',
      '通过申请',
      {
        inputValue: item.orgName || item.projectOrgName || '',
        inputPlaceholder: '单位全称',
        inputPattern: /\S/,
        inputErrorMessage: '请填写单位',
        confirmButtonText: '通过'
      }
    )
    return String(input.value || '').trim()
  } catch {
    return undefined // 取消
  }
}

/* 单位名和项目已有单位不同：不自动合并，让审核人选 */
const askMergeOrNew = async (requested: string, existing: string) => {
  try {
    await ElMessageBox.confirm(
      `申请单位「${requested}」与项目已有单位「${existing}」名字不同。` +
        '是同一家公司就并入已有单位；确实是另一家公司就算作新单位（两家的资料互相看不到）。',
      '单位名不一致',
      {
        confirmButtonText: `并入「${existing}」`,
        cancelButtonText: '算作新单位',
        distinguishCancelAndClose: true,
        type: 'warning'
      }
    )
    return 'merge' as const
  } catch (action) {
    return action === 'cancel' ? ('new' as const) : undefined
  }
}

const submitReview = async (
  item: RegistrationRequestItem,
  payload: { approved: boolean; reason?: string; orgName?: string; confirmNewOrg?: boolean }
): Promise<boolean> => {
  try {
    const res = await reviewRegistrationRequestApi(props.projectId, item.id, payload)
    if (!res) return false
    if (!payload.approved) {
      ElMessage.success('已拒绝，申请人在链接里能看到理由')
    } else {
      const notes = [
        res.data.orgCreated ? `已新建单位「${res.data.orgName}」` : '',
        res.data.projectOrgFilled ? '已写入项目参建单位' : ''
      ].filter(Boolean)
      ElMessage.success(`已通过，账号已创建${notes.length ? '；' + notes.join('，') : ''}`)
    }
    return true
  } catch (error) {
    const data = errorData(error)
    if (payload.approved && data?.reason === 'orgMismatch') {
      const choice = await askMergeOrNew(
        String(data.requestedOrgName || payload.orgName || ''),
        String(data.projectOrgName || '')
      )
      if (!choice) return false
      return submitReview(
        item,
        choice === 'merge'
          ? { approved: true, orgName: String(data.projectOrgName || '') }
          : { approved: true, orgName: payload.orgName, confirmNewOrg: true }
      )
    }
    ElMessage.error(getAicheckErrorMessage(error, '审核失败。'))
    return false
  }
}

const handleReview = async (item: RegistrationRequestItem, approved: boolean) => {
  let reason = ''
  let orgName: string | undefined
  if (!approved) {
    /* 拒绝必须写理由。不写的话申请人只看到「被拒了」，不知道要改什么，
       他会原样再提一次——两边都白忙。 */
    try {
      const input = await ElMessageBox.prompt(
        `拒绝 ${item.displayName || item.username} 的申请，请说明原因（申请人在链接里能看到）`,
        '拒绝申请',
        {
          inputPlaceholder: '例如：单位名称写错了，请填公司全称',
          inputPattern: /\S/,
          inputErrorMessage: '必须填写理由'
        }
      )
      reason = String(input.value || '').trim()
    } catch {
      return // 用户取消
    }
  } else {
    orgName = await askOrgName(item)
    if (orgName === undefined) return
  }
  reviewing.value = item.id
  try {
    const done = await submitReview(item, approved ? { approved, orgName } : { approved, reason })
    if (done) await Promise.all([loadRequests(), loadMembers()])
  } finally {
    reviewing.value = ''
  }
}
</script>

<template>
  <section class="project-registration">
    <h4>{{ projectName }} · 邀请成员</h4>
    <p class="share-intro">
      把下面的链接或二维码发到施工、无损、建设单位的群里。对方打开后自己填姓名、单位和角色，
      你在这里点「通过」就加入本项目——不用先建组织和用户。
    </p>

    <ElButton :loading="linkLoading" @click="handleCreateLink()">
      {{ link ? '重新生成链接' : '生成邀请链接' }}
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
        <small>手机扫码即可打开申请页</small>
      </div>
      <!-- 有效期和次数都要写出来：链接会被转发、被截图 -->
      <small
        >有效期至 {{ formatExpiry(linkExpiresAt) }}，最多可注册
        {{ linkMaxUses }} 人；提交后需审核通过才生效</small
      >
    </div>

    <ElAlert
      v-if="!listLoading && !requests.length"
      class="registration-empty"
      type="info"
      title="还没有人提交加入申请。"
      :closable="false"
      show-icon
    />
    <ElTable v-else v-loading="listLoading" :data="requests" class="registration-table">
      <ElTableColumn prop="username" label="用户名" min-width="100" />
      <ElTableColumn prop="displayName" label="姓名" min-width="80" />
      <ElTableColumn label="单位" min-width="150">
        <template #default="{ row }">
          <span>{{ orgOf(row) || '未填写' }}</span>
          <!-- 和项目已登记的单位名字不同：审核时要选并入还是新单位 -->
          <small v-if="row.status === '待审核' && orgDiffers(row)" class="org-diff">
            与项目已有「{{ row.projectOrgName }}」不同
          </small>
        </template>
      </ElTableColumn>
      <ElTableColumn label="申请角色" width="90">
        <template #default="{ row }">{{ ROLE_LABELS[row.role] || row.role }}</template>
      </ElTableColumn>
      <ElTableColumn prop="createdAt" label="提交时间" width="150" />
      <ElTableColumn label="状态" width="110">
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
      <ElTableColumn label="操作" width="110" fixed="right">
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

    <h5 class="members-title">已加入的成员</h5>
    <p class="members-intro">成员忘了密码，在这里点「重置密码」，把临时密码告诉对方即可。</p>
    <ElAlert
      v-if="!membersLoading && !members.length"
      type="info"
      title="还没有施工、无损或建设单位的成员。"
      :closable="false"
      show-icon
    />
    <ElTable v-else v-loading="membersLoading" :data="members" class="registration-table">
      <ElTableColumn prop="name" label="姓名" min-width="80" />
      <ElTableColumn prop="username" label="用户名" min-width="100" />
      <ElTableColumn label="角色" width="90">
        <template #default="{ row }">{{ ROLE_LABELS[row.role] || row.role }}</template>
      </ElTableColumn>
      <ElTableColumn prop="orgName" label="单位" min-width="140" />
      <ElTableColumn label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <ElButton
            v-if="row.canResetPassword"
            link
            type="primary"
            :loading="resetting === row.userId"
            @click="handleResetPassword(row)"
          >
            重置密码
          </ElButton>
          <small v-else class="reviewed-hint">{{ row.resetBlockedReason }}</small>
          <small v-if="row.mustChangePassword" class="reviewed-hint">待对方改密码</small>
        </template>
      </ElTableColumn>
    </ElTable>

    <!-- 临时密码只在这里出现一次：关掉就看不到了，所以给复制按钮和一句提醒 -->
    <ElDialog
      :model-value="Boolean(resetResult)"
      title="临时密码已生成"
      width="min(420px, 92vw)"
      append-to-body
      @close="resetResult = undefined"
    >
      <template v-if="resetResult">
        <p>请把下面的账号和临时密码告诉「{{ resetResult.name }}」：</p>
        <dl class="reset-result">
          <dt>账号</dt>
          <dd>{{ resetResult.username }}</dd>
          <dt>临时密码</dt>
          <dd class="reset-password">{{ resetResult.password }}</dd>
        </dl>
        <p class="members-intro"
          >对方登录后系统会要求改成自己的密码。这个窗口关掉后临时密码不会再显示。</p
        >
      </template>
      <template #footer>
        <ElButton @click="copyResetMessage">复制发给对方</ElButton>
        <ElButton type="primary" @click="resetResult = undefined">好了</ElButton>
      </template>
    </ElDialog>
  </section>
</template>

<style scoped>
.project-registration h4 {
  margin: 0 0 12px;
}

.share-intro {
  margin: 0 0 12px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

.org-diff {
  display: block;
  color: var(--el-color-warning);
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
  padding: 6px;
  margin: 0 auto 4px;
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

.members-title {
  margin: 20px 0 4px;
  font-size: 14px;
}

.members-intro {
  margin: 0 0 8px;
  color: var(--el-text-color-secondary);
}

.reset-result {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 12px;
  margin: 12px 0;
}

.reset-result dt {
  color: var(--el-text-color-secondary);
}

.reset-result dd {
  margin: 0;
}

.reset-password {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 22px;
  letter-spacing: 2px;
}

.pending-hint {
  margin: 10px 0 0;
  color: var(--el-color-warning);
}
</style>
