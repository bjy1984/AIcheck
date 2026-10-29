import { ref, watch, type Ref } from 'vue'
import request from '@/axios'
import type { RectificationItem, RoleCode } from '@/types/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'

export const useProjectRectifications = (projectId: Ref<string>, role: Ref<RoleCode>) => {
  const items = ref<RectificationItem[]>([])
  const issue = ref('')
  const loading = ref(false)
  const loaded = ref(false)
  let generation = 0
  watch(
    [projectId, role],
    () => {
      generation++
      items.value = []
      issue.value = ''
      loading.value = false
      loaded.value = false
    },
    { flush: 'sync' }
  )
  const load = async () => {
    if (!projectId.value || role.value !== 'contractor') return
    const project = projectId.value
    const token = ++generation
    loading.value = true
    issue.value = ''
    try {
      const all: RectificationItem[] = []
      for (let page = 1; ; page++) {
        const res = await request.get<{ items: RectificationItem[]; total: number }>({
          url: `/api/projects/${encodeURIComponent(project)}/rectifications`,
          params: { page, pageSize: 100 }
        })
        if (token !== generation) return
        if (!res?.data || !Array.isArray(res.data.items)) throw new Error('补正清单返回格式不完整')
        all.push(...res.data.items)
        if (all.length >= res.data.total || !res.data.items.length) break
      }
      items.value = all
      loaded.value = true
    } catch (error) {
      if (token === generation)
        issue.value =
          getAicheckErrorMessage(error, '项目补正清单加载失败，请重试。') +
          (items.value.length ? ' 当前显示上次成功加载的清单。' : '')
    } finally {
      if (token === generation) loading.value = false
    }
  }
  return {
    projectRectifications: items,
    projectRectificationIssue: issue,
    projectRectificationLoading: loading,
    projectRectificationLoaded: loaded,
    loadProjectRectifications: load
  }
}
