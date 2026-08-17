<script setup lang="ts">
/**
 * 组织负责人：生成邀请链接、调整本组织成员角色（0817 第 4、5 条）。
 *
 * ## 界面只是入口，闸门在服务端
 *
 * 这里不做任何权限判断的**依据**——按钮禁用、选项过滤都只是省得用户白点。
 * 真正拦住越权的是服务端（apps/api/org_delegation_routes.py）：
 * 跨组织、授出 admin/fde、改自己，一律 403。
 *
 * **前端的禁用不能当成安全措施**：改一行请求就绕过去了。
 * 这两层的分工要写清楚，免得后人以为「界面上没有这个选项」就等于管住了。
 *
 * ## 邀请链接展示的两个决定
 *
 * - 明确写出有效期。链接会被转发、被截图、被贴进群里，
 *   看的人得知道它什么时候作废。
 * - 只在生成的那一刻显示一次，不做历史列表：
 *   一份能随时翻出来的链接清单，等于一堆长期有效的入口。
 */
import { computed, ref } from 'vue'
import { ElAlert, ElButton, ElInput, ElMessage, ElOption, ElSelect, ElTag } from 'element-plus'

import { assignOrgMemberRoleApi, createOrgInvitationApi, type AdminUser } from '@/api/aicheck'
import type { RoleCode } from '@/types/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'

const props = defineProps<{
  orgId: string
  orgName: string
  members: AdminUser[]
  /** 当前登录人的 id。用来在界面上把「自己」标出来——服务端也会拒。 */
  currentUserId: string
}>()

const emit = defineEmits<{ changed: [] }>()

/* 能授出的角色。admin / fde 不在里面——服务端也会拒，
   但选项里就不该出现：给一个必然失败的选择只是浪费用户一次点击。 */
const ASSIGNABLE_ROLES: Array<{ value: RoleCode; label: string }> = [
  { value: 'contractor', label: '施工单位' },
  { value: 'inspection', label: '监检人员' },
  { value: 'ndt', label: '无损检测' },
  { value: 'owner', label: '建设单位' }
]

const inviteRole = ref<RoleCode>('contractor')
const inviteLoading = ref(false)
const inviteLink = ref('')
const inviteExpiresAt = ref('')

const assigning = ref('')

const orgMembers = computed(() =>
  props.members.filter((item) => String(item.orgId || '') === String(props.orgId))
)

const handleCreateInvite = async () => {
  inviteLoading.value = true
  inviteLink.value = ''
  try {
    const res = await createOrgInvitationApi(props.orgId, inviteRole.value)
    if (!res) return
    // 组成收件人真正要点的地址，而不是把裸 token 丢给用户让他自己拼
    inviteLink.value = `${window.location.origin}/#/invite/${res.data.token}`
    inviteExpiresAt.value = res.data.expiresAt
    ElMessage.success('邀请链接已生成')
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '生成邀请链接失败。'))
  } finally {
    inviteLoading.value = false
  }
}

const handleCopy = async () => {
  try {
    await navigator.clipboard.writeText(inviteLink.value)
    ElMessage.success('已复制')
  } catch {
    // 复制失败不是错误，链接就在输入框里，用户可以自己选中
    ElMessage.info('复制失败，请手动选中链接复制')
  }
}

const handleAssign = async (member: AdminUser, role: RoleCode) => {
  if (role === member.role) return
  assigning.value = member.id
  try {
    const res = await assignOrgMemberRoleApi(props.orgId, member.id, role)
    if (!res) return
    ElMessage.success(`已将 ${member.name} 的角色改为 ${role}`)
    emit('changed')
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '调整角色失败。'))
  } finally {
    assigning.value = ''
  }
}
</script>

<template>
  <section class="org-delegation">
    <h4>{{ orgName }} · 成员与邀请</h4>

    <!-- 邀请链接 -->
    <div class="invite-row">
      <ElSelect v-model="inviteRole" class="invite-role">
        <ElOption
          v-for="item in ASSIGNABLE_ROLES"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </ElSelect>
      <ElButton type="primary" :loading="inviteLoading" @click="handleCreateInvite">
        生成邀请链接
      </ElButton>
    </div>

    <div v-if="inviteLink" class="invite-result">
      <ElInput :model-value="inviteLink" readonly>
        <template #append>
          <ElButton @click="handleCopy">复制</ElButton>
        </template>
      </ElInput>
      <!-- 有效期必须写出来：链接会被转发、被截图，看的人得知道它什么时候作废 -->
      <small>此链接只能使用一次，有效期至 {{ inviteExpiresAt }}</small>
    </div>

    <!-- 成员角色 -->
    <ElAlert
      v-if="!orgMembers.length"
      type="info"
      title="本组织还没有成员。可以用上面的邀请链接把人拉进来。"
      :closable="false"
      show-icon
    />
    <ul v-else class="member-list">
      <li v-for="member in orgMembers" :key="member.id">
        <span class="member-name">
          {{ member.name }}
          <ElTag v-if="member.isOrgLeader" size="small" type="warning" effect="plain">负责人</ElTag>
          <ElTag v-if="member.id === currentUserId" size="small" effect="plain">本人</ElTag>
        </span>
        <ElSelect
          :model-value="member.role"
          class="member-role"
          :loading="assigning === member.id"
          :disabled="member.id === currentUserId || member.isOrgLeader"
          :title="
            member.id === currentUserId
              ? '不能修改自己的角色'
              : member.isOrgLeader
                ? '负责人的角色由系统管理员调整'
                : ''
          "
          @change="(value: RoleCode) => handleAssign(member, value)"
        >
          <ElOption
            v-for="item in ASSIGNABLE_ROLES"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </ElSelect>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.org-delegation h4 {
  margin: 0 0 12px;
}

.invite-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.invite-role {
  width: 140px;
}

.invite-result {
  margin: 10px 0 16px;
}

.invite-result small {
  display: block;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
}

.member-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.member-list li {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.member-name {
  display: flex;
  gap: 6px;
  align-items: center;
}

.member-role {
  width: 150px;
}
</style>
