import type { Project } from '@/types/aicheck'

/** 工程上明确写的 Jev 插件开关；没写（还在用旧的环境变量白名单）时是 undefined。 */
export const explicitJevSetting = (project: Pick<Project, 'reviewPlugins'>) => {
  const enabled = project.reviewPlugins?.jev?.enabled
  return typeof enabled === 'boolean' ? enabled : undefined
}

/**
 * 保存工程时要不要带上插件设置：只有管理员动过开关才发。
 * 没动过就不发——否则还靠旧白名单启用的工程会被存成明确「关闭」。
 */
export const reviewPluginPatch = (initial: boolean | undefined, current: boolean) =>
  initial === current || (initial === undefined && !current)
    ? {}
    : { reviewPlugins: { jev: { enabled: current } } }
