import { computed, ref, watch, type Ref } from 'vue'
export const useWorkstationFilter = (
  role: Readonly<Ref<string>>,
  projectId: Readonly<Ref<string>>
) => {
  const labNavigationEnabled = computed(
    () =>
      import.meta.env.VITE_AICHECK_WORKSTATIONS_ENABLED === 'true' && role.value === 'inspection'
  )
  const labStation = ref('')
  const labNodeStatus = ref('')
  watch(projectId, () => {
    labStation.value = ''
    labNodeStatus.value = ''
  })
  return { labNavigationEnabled, labStation, labNodeStatus }
}
