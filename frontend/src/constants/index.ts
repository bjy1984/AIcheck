/**
 * 请求成功状态码
 */
export const SUCCESS_CODE = 0

/**
 * 请求contentType
 */
export const CONTENT_TYPE: AxiosContentType = 'application/json'

/**
 * 请求超时时间
 */
export const REQUEST_TIMEOUT = 60000

/**
 * 不重定向白名单
 */
/* 邀请注册页必须免登录（0817 第 4 条）：**收件人本来就还没有账号**。
   漏掉它的话，路由守卫会把他弹回登录页——一个专门发给「还没账号的人」的
   链接，却要求先登录，这条路就整个走不通了。 */
export const NO_REDIRECT_WHITE_LIST = ['/login', '/invite']

/**
 * 不重置路由白名单
 */
export const NO_RESET_WHITE_LIST = [
  'Redirect',
  'RedirectWrap',
  'Login',
  'ChangePassword',
  'NoFind',
  'Root'
]

/**
 * 表格默认过滤列设置字段
 */
export const DEFAULT_FILTER_COLUMN = ['expand', 'selection']

/**
 * 是否根据headers->content-type自动转换数据格式
 */
export const TRANSFORM_REQUEST_DATA = true

/**
 * 全局图标前缀
 */
export const ICON_PREFIX = 'vi-'
