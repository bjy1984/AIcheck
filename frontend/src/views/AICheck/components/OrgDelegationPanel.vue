<script setup lang="ts">
/**
 * 组织负责人：调整本组织成员角色（0817 第 5 条）。
 *
 * ## 邀请链接已经从这里撤掉
 *
 * 注册统一走「按项目发链接 → 自选角色 → 项目负责人审核」
 * （ProjectRegistrationPanel）。两套并存的话，一条即时生效、一条要审核，
 * **同一个系统里两种「注册」意味着两种安全边界**，而看界面的人分不出
 * 自己走的是哪一条；组织邀请又是更宽的那条，留着等于给「必须审核」
 * 留了个绕过口。
 *
 * ## 界面只是入口，闸门在服务端
 *
 * 这里不做任何权限判断的**依据**——按钮禁用、选项过滤都只是省得用户白点。
 * 真正拦住越权的是服务端（apps/api/org_delegation_routes.py）：
 * 跨组织、授出 admin/fde、改自己，一律 403。
 *
 * **前端的禁用不能当成安全措施**：改一行请求就绕过去了。
 * 这两层的分工要写清楚，免得后人以为「界面上没有这个选项」就等于管住了。
 * */
import { computed, ref } from 'vue'
import { ElAlert, ElMessage, ElOption, ElSelect, ElTag } from 'element-plus'

import { assignOrgMemberRoleApi, type AdminUser } from '@/api/aicheck'
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

const assigning = ref('')

const orgMembers = computed(() =>
  props.members.filter((item) => String(item.orgId || '') === String(props.orgId))
)

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
    <h4>{{ orgName }} · 成员角色</h4>

    <!-- 成员角色 -->
    <ElAlert
      v-if="!orgMembers.length"
      type="info"
      title="本组织还没有成员。新成员通过项目注册链接加入并经审核后出现在这里。"
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
