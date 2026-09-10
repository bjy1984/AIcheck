import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { ProjectTreePayload } from '@/api/aicheck'
import { getHandoffNodeStatuses, type HandoffNodeStatuses } from '@/api/aicheck/reviewHandoffs'
import { handoffStatusError } from './handoffStatusError'
import { withHandoffStatuses } from './handoffNodeStatuses'

export const useHandoffNodeStatuses = (props: {
  groups: ProjectTreePayload['groups']
  enabled: boolean
}) => {
  const report = ref<HandoffNodeStatuses>()
  const busy = ref(false)
  const error = ref('')
  let generation = 0
  const refresh = async () => {
    const attempt = ++generation
    report.value = undefined
    error.value = ''
    busy.value = false
    const projects = new Set(
      props.groups.flatMap((group) => group.nodes.map((node) => node.projectId))
    )
    const projectId = projects.size === 1 ? [...projects][0] : ''
    if (!props.enabled || !projectId) return
    busy.value = true
    try {
      const response = await getHandoffNodeStatuses(projectId)
      if (attempt !== generation) return
      if (response.data.projectId !== projectId || !Array.isArray(response.data.items))
        throw new Error('invalid project response')
      report.value = response.data
    } catch (cause) {
      if (attempt === generation) error.value = handoffStatusError(cause)
    } finally {
      if (attempt === generation) busy.value = false
    }
  }
  watch(() => [props.enabled, props.groups], refresh, { immediate: true })
  onBeforeUnmount(() => {
    generation++
  })
  return {
    busy,
    error,
    refresh,
    groups: computed(() =>
      props.enabled ? withHandoffStatuses(props.groups, report.value) : props.groups
    )
  }
}
