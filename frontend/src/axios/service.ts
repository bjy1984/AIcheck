import axios, { AxiosError } from 'axios'
import { defaultRequestInterceptors, defaultResponseInterceptors } from './config'

import { AxiosInstance, InternalAxiosRequestConfig, RequestConfig, AxiosResponse } from './types'
import { ElMessage } from 'element-plus'
import { REQUEST_TIMEOUT } from '@/constants'
import { getAicheckErrorMessage, recordAicheckBusinessError } from '@/utils/aicheckError'
import { useUserStoreWithOut } from '@/store/modules/user'
import router from '@/router'

export const PATH_URL = import.meta.env.VITE_API_BASE_PATH

const abortControllerMap: Map<string, AbortController> = new Map()

const axiosInstance: AxiosInstance = axios.create({
  timeout: REQUEST_TIMEOUT,
  baseURL: PATH_URL
})

axiosInstance.interceptors.request.use((res: InternalAxiosRequestConfig) => {
  const controller = new AbortController()
  const url = res.url || ''
  res.signal = controller.signal
  abortControllerMap.set(
    import.meta.env.VITE_USE_MOCK === 'true' ? url.replace('/mock', '') : url,
    controller
  )
  return res
})

axiosInstance.interceptors.response.use(
  (res: AxiosResponse) => {
    const url = res.config.url || ''
    abortControllerMap.delete(url)
    // 这里不能做任何处理，否则后面的 interceptors 拿不到完整的上下文了
    return res
  },
  (error: AxiosError) => {
    const responseData = error.response?.data as
      | { code?: number; message?: string; data?: { reason?: string } }
      | undefined
    const silentHttpError =
      error.config?.headers?.['X-Silent-Http-Error'] === 'true' ||
      error.config?.headers?.['x-silent-http-error'] === 'true'
    if (responseData) {
      recordAicheckBusinessError(responseData, {
        method: error.config?.method,
        url: error.config?.url
      })
      if (responseData.data?.reason === 'PASSWORD_CHANGE_REQUIRED') {
        const userStore = useUserStoreWithOut()
        if (userStore.getUserInfo) {
          userStore.setUserInfo({ ...userStore.getUserInfo, mustChangePassword: true })
        }
        if (router.currentRoute.value.path !== '/change-password') {
          router.replace('/change-password').catch(() => undefined)
        }
      }
    }
    if (!silentHttpError) {
      ElMessage.error(
        getAicheckErrorMessage(error, responseData?.message || error.message || '请求失败')
      )
    }
    return Promise.reject(error)
  }
)

axiosInstance.interceptors.request.use(defaultRequestInterceptors)
axiosInstance.interceptors.response.use(defaultResponseInterceptors)

const service = {
  request: (config: RequestConfig) => {
    return new Promise((resolve, reject) => {
      if (config.interceptors?.requestInterceptors) {
        config = config.interceptors.requestInterceptors(config as any)
      }

      axiosInstance
        .request(config)
        .then((res) => {
          resolve(res)
        })
        .catch((err: any) => {
          reject(err)
        })
    })
  },
  cancelRequest: (url: string | string[]) => {
    const urlList = Array.isArray(url) ? url : [url]
    for (const _url of urlList) {
      abortControllerMap.get(_url)?.abort()
      abortControllerMap.delete(_url)
    }
  },
  cancelAllRequest() {
    for (const [_, controller] of abortControllerMap) {
      controller.abort()
    }
    abortControllerMap.clear()
  }
}

export default service
