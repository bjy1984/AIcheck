import type { ReviewBRun } from '@/types/ai-review-b'

export const INPUT_CHANGED_MESSAGE =
  '本次复核使用的文件范围、OCR 或人工修正已改变，审查已停止。请核对当前资料后重新发起复核；新任务将使用当前版本，历史记录保留。'

export function needsFreshReview(run: ReviewBRun | null | undefined): boolean {
  return (
    ['failed', '失败'].includes(run?.status || '') &&
    run?.errorCode === 'REVIEW_INPUT_CHANGED_RECREATE_RUN'
  )
}

export const PIPELINE_CONFLICT_MESSAGE =
  '选取资料中同一管线号的设计参数存在冲突，审查已停止。请核对原文与文件版本，修正冲突后重新发起复核；重复运行不会自动解决冲突。'

export function hasPipelineConflict(run: ReviewBRun | null | undefined): boolean {
  return (
    ['failed', '失败'].includes(run?.status || '') &&
    run?.errorCode === 'REVIEW_PIPELINE_FACTS_CONFLICT'
  )
}
