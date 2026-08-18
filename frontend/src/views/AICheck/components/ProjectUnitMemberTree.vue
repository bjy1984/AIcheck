<script setup lang="ts">
/**
 * 参建单位与成员合并成一棵树：单位是父行，它的人是子行。
 *
 * ## 为什么合并
 *
 * 原先是上下两张表：上面「参建单位」（只读，单位名/类型/联系人/电话），
 * 下面「成员授权」（可增可改，姓名/组织/角色/节点范围/动作）。
 * 两者靠 orgName 这串文字对应——**看不出某个成员属于哪个参建单位**，
 * 要自己拿组织名去上面那张表里找。人一多就对不过来。
 *
 * ## 但不是平铺成一张
 *
 * 单位有它自己的信息（类型、联系人、电话），平铺之后这些要么消失，
 * 要么在每一行里重复一遍。所以做成树：**保留两个层级，只是放进同一个视图**。
 *
 * ## 挂不上单位的人要单独列出来
 *
 * 成员的 orgName 和参建单位对不上时，如果只按单位分组，这些人就**消失了**
 * ——而他们恰恰是最需要被看到的（组织名写错、单位没登记）。
 * 所以有一组「未归入参建单位」，并且写明原因。
 */
import { computed } from 'vue'
import { ElButton, ElTable, ElTableColumn, ElTag } from 'element-plus'

import type { ProjectMember } from '@/api/aicheck'

type ParticipantUnit = {
  unitType: string
  unitName: string
  contactName?: string
  contactPhone?: string
}

type Row = {
  id: string
  kind: 'unit' | 'member'
  label: string
  unitType?: string
  contact?: string
  role?: string
  status?: string
  nodeScope?: number[] | null
  actions?: string[]
  isProjectLeader?: boolean
  member?: ProjectMember
  children?: Row[]
}

const props = defineProps<{
  units: ParticipantUnit[]
  members: ProjectMember[]
  readOnly?: boolean
  formatUnitType: (value: string) => string
  formatNodeScope: (value: number[] | null | undefined) => string
  roleLabel: (value: string) => string
}>()

const emit = defineEmits<{
  edit: [member: ProjectMember]
  'toggle-leader': [member: ProjectMember, next: boolean]
  /* 停用和删除是原来那张表就有的功能。换布局时把它们弄丢过一次——
   **功能不能因为改了布局就消失**，那种丢失没有任何报错。 */
  'toggle-status': [member: ProjectMember]
  remove: [member: ProjectMember]
}>()

const memberRow = (member: ProjectMember): Row => ({
  id: `member-${member.id}`,
  kind: 'member',
  label: member.name,
  role: member.role,
  status: member.status,
  nodeScope: member.nodeScope,
  actions: member.actions,
  isProjectLeader: Boolean(member.isProjectLeader),
  member
})

const rows = computed<Row[]>(() => {
  const used = new Set<string>()
  const unitRows: Row[] = props.units.map((unit) => {
    const children = props.members.filter((member) => {
      const hit = String(member.orgName || '') === String(unit.unitName || '')
      if (hit) used.add(member.id)
      return hit
    })
    return {
      id: `unit-${unit.unitType}-${unit.unitName}`,
      kind: 'unit',
      label: unit.unitName,
      unitType: unit.unitType,
      contact: [unit.contactName, unit.contactPhone].filter(Boolean).join(' · '),
      children: children.map(memberRow)
    }
  })

  /* 对不上任何参建单位的人。只按单位分组的话他们会**消失**——
     而组织名写错、单位没登记，恰恰是最该被看到的情况。 */
  const orphans = props.members.filter((member) => !used.has(member.id))
  if (orphans.length) {
    unitRows.push({
      id: 'unit-__orphan__',
      kind: 'unit',
      label: '未归入参建单位',
      unitType: '',
      contact: '这些成员的组织名与参建单位对不上，请核对组织名或补登参建单位',
      children: orphans.map(memberRow)
    })
  }
  return unitRows
})

const leaderCountOfRole = (role: string) =>
  props.members.filter((member) => member.role === role && member.isProjectLeader).length
</script>

<template>
  <ElTable
    :data="rows"
    row-key="id"
    border
    default-expand-all
    :tree-props="{ children: 'children' }"
  >
    <ElTableColumn label="单位 / 成员" min-width="240" show-overflow-tooltip>
      <template #default="{ row }">
        <template v-if="row.kind === 'unit'">
          <strong>{{ row.label }}</strong>
          <ElTag v-if="row.unitType" size="small" effect="plain" class="unit-type">
            {{ formatUnitType(row.unitType) }}
          </ElTag>
          <ElTag v-if="!row.children.length" size="small" type="info" effect="plain">
            暂无成员
          </ElTag>
        </template>
        <template v-else>
          {{ row.label }}
          <!-- 同一角色可以有多个负责人：现场本来就有 AB 角和轮班 -->
          <ElTag v-if="row.isProjectLeader" size="small" type="warning" effect="plain">
            负责人
          </ElTag>
        </template>
      </template>
    </ElTableColumn>

    <ElTableColumn label="角色 / 联系人" min-width="180" show-overflow-tooltip>
      <template #default="{ row }">
        <span v-if="row.kind === 'unit'" class="unit-contact">{{ row.contact || '--' }}</span>
        <ElTag v-else effect="plain">{{ roleLabel(row.role) }}</ElTag>
      </template>
    </ElTableColumn>

    <ElTableColumn label="节点范围" min-width="150">
      <template #default="{ row }">
        <span v-if="row.kind === 'member'">{{ formatNodeScope(row.nodeScope) }}</span>
      </template>
    </ElTableColumn>

    <ElTableColumn label="动作" min-width="200">
      <template #default="{ row }">
        <div v-if="row.kind === 'member'" class="tag-list">
          <ElTag
            v-for="action in row.actions.slice(0, 4)"
            :key="action"
            size="small"
            effect="plain"
          >
            {{ action }}
          </ElTag>
          <ElTag v-if="row.actions.length > 4" size="small" type="info" effect="plain">
            +{{ row.actions.length - 4 }}
          </ElTag>
        </div>
      </template>
    </ElTableColumn>

    <ElTableColumn label="状态" width="88">
      <template #default="{ row }">
        <ElTag
          v-if="row.kind === 'member'"
          size="small"
          effect="plain"
          :type="row.status === '启用' ? 'success' : 'info'"
        >
          {{ row.status }}
        </ElTag>
      </template>
    </ElTableColumn>

    <ElTableColumn label="操作" width="270" fixed="right">
      <template #default="{ row }">
        <template v-if="row.kind === 'member' && !readOnly">
          <ElButton link type="primary" @click="emit('edit', row.member)">编辑</ElButton>
          <!-- 取消最后一个负责人是允许的，但要让人知道之后没人能审注册申请了。
               直接禁用会让人以为坏了；不提示则会悄悄失去审批能力。 -->
          <ElButton
            link
            :type="row.isProjectLeader ? 'warning' : 'primary'"
            :title="
              row.isProjectLeader && leaderCountOfRole(row.role) <= 1
                ? '这是该角色最后一位负责人，取消后将没有人能审核注册申请'
                : ''
            "
            @click="emit('toggle-leader', row.member, !row.isProjectLeader)"
          >
            {{ row.isProjectLeader ? '取消负责人' : '设为负责人' }}
          </ElButton>
          <ElButton link type="primary" @click="emit('toggle-status', row.member)">
            {{ row.status === '启用' ? '停用' : '启用' }}
          </ElButton>
          <ElButton link type="danger" @click="emit('remove', row.member)">删除</ElButton>
        </template>
      </template>
    </ElTableColumn>
  </ElTable>
</template>

<style scoped>
.unit-type {
  margin-left: 6px;
}

.unit-contact {
  color: var(--el-text-color-secondary);
}

.tag-list {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
</style>
