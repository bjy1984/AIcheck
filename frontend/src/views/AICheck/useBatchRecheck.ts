/**
 * 一键审查的状态与调用（0817 第 3 条）。
 *
 * ## 为什么抽出来
 *
 * Workbench.vue 有行数棘轮。棘轮的用意就是逼新功能不要再往那个大文件里堆
 * ——直接写进去会触发棘轮，而抬高上限等于把这条约束取消掉。
 *
 * ## 这段逻辑唯一的要点
 *
 * **跳过的节点必须回给界面。**
 *
 * 只报「已发起 N 个」的话，剩下的去哪了没人知道，监检会以为全跑过了
 * ——而「漏掉一个也不会有人发现」正是这个功能要消灭的状态。
 * 报喜不报忧的批量操作，比不做批量更危险。
 *
 * 一个都没发起时更要说清楚：那种情况在界面上和「点了没反应」长得一样。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { requestAiRecheckBatchApi, type BatchRecheckPayload } from '@/api/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'

export function useBatchRecheck(options: {
  projectId: () => string
  etag: () => string | undefined
  onFinished: () => Promise<void> | void
}) {
  const batchRecheckLoading = ref(false)
  const batchRecheckResult = ref<BatchRecheckPayload | undefined>(undefined)

  const handleAiRecheckBatch = async () => {
    const projectId = options.projectId()
    if (!projectId) return
    batchRecheckLoading.value = true
    batchRecheckResult.value = undefined
    try {
      const res = await requestAiRecheckBatchApi(
        projectId,
        {},
        { etag: options.etag(), silentBusinessError: true, silentHttpError: true }
      )
      if (!res) {
        ElMessage.error('一键审查失败，请稍后重试。')
        return
      }
      batchRecheckResult.value = res.data
      const { startedCount, skippedCount } = res.data
      if (startedCount) {
        ElMessage.success(`已发起 ${startedCount} 个节点；${skippedCount} 个已跳过，见下方说明`)
      } else {
        // 一个都没发起时更要说清楚，否则看起来像「点了没反应」
        ElMessage.warning(`没有可发起的节点：${skippedCount} 个已跳过，见下方说明`)
      }
      await options.onFinished()
    } catch (error) {
      ElMessage.error(getAicheckErrorMessage(error, '一键审查失败，请稍后重试。'))
    } finally {
      batchRecheckLoading.value = false
    }
  }

  return { batchRecheckLoading, batchRecheckResult, handleAiRecheckBatch }
}
