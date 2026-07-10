<script setup lang="tsx">
import { reactive, ref, watch, onMounted, unref } from 'vue'
import { Form, FormSchema } from '@/components/Form'
import { useI18n } from '@/hooks/web/useI18n'
import { ElCheckbox, ElLink, ElAlert } from 'element-plus'
import { useForm } from '@/hooks/web/useForm'
import { loginApi, getTestRoleApi, getAdminRoleApi } from '@/api/login'
import { useAppStore } from '@/store/modules/app'
import { usePermissionStore } from '@/store/modules/permission'
import { useRouter } from 'vue-router'
import type { RouteLocationNormalizedLoaded, RouteRecordRaw } from 'vue-router'
import type { UserLoginType } from '@/api/login/types'
import { useValidator } from '@/hooks/web/useValidator'
import { Icon } from '@/components/Icon'
import { useUserStore } from '@/store/modules/user'
import { BaseButton } from '@/components/Button'
import { resolveRoleEntryPath } from '@/utils/roleAccess'

const { required } = useValidator()

const emit = defineEmits(['to-register'])

const appStore = useAppStore()

const userStore = useUserStore()

const permissionStore = usePermissionStore()

const { currentRoute, addRoute, push } = useRouter()

const { t } = useI18n()

const rules = {
  username: [required()],
  password: [required()]
}

const schema = reactive<FormSchema[]>([
  {
    field: 'title',
    colProps: {
      span: 24
    },
    formItemProps: {
      slots: {
        default: () => {
          return (
            <div class="w-[100%]">
              <h2 class="auth-form-title">{t('login.login')}</h2>
            </div>
          )
        }
      }
    }
  },
  {
    field: 'username',
    label: t('login.username'),
    // value: 'admin',
    component: 'Input',
    colProps: {
      span: 24
    },
    componentProps: {
      placeholder: '请输入账号',
      prefixIcon: <Icon icon="vi-ep:user" />
    }
  },
  {
    field: 'password',
    label: t('login.password'),
    // value: 'admin',
    component: 'InputPassword',
    colProps: {
      span: 24
    },
    componentProps: {
      style: {
        width: '100%'
      },
      placeholder: '请输入密码',
      prefixIcon: <Icon icon="vi-ep:lock" />,
      // 按下enter键触发登录
      onKeydown: (_e: any) => {
        if (_e.key === 'Enter') {
          _e.stopPropagation() // 阻止事件冒泡
          signIn()
        }
      }
    }
  },
  {
    field: 'error',
    colProps: {
      span: 24
    },
    formItemProps: {
      slots: {
        default: () => {
          if (!unref(errorMessage)) return null
          return (
            <ElAlert
              title={unref(errorMessage)}
              type="error"
              show-icon
              closable
              onClose={() => {
                errorMessage.value = ''
              }}
            />
          )
        }
      }
    }
  },
  {
    field: 'tool',
    colProps: {
      span: 24
    },
    formItemProps: {
      slots: {
        default: () => {
          return (
            <>
              <div class="flex justify-between items-center w-[100%]">
                <ElCheckbox v-model={remember.value} label={t('login.remember')} size="small" />
                <ElLink type="primary" underline={false}>
                  {t('login.forgetPassword')}
                </ElLink>
              </div>
            </>
          )
        }
      }
    }
  },
  {
    field: 'login',
    colProps: {
      span: 24
    },
    formItemProps: {
      slots: {
        default: () => {
          return (
            <>
              <div class="w-[100%]">
                <BaseButton
                  loading={loading.value}
                  type="primary"
                  class="w-[100%] auth-submit-button"
                  onClick={signIn}
                >
                  {t('login.login')}
                </BaseButton>
              </div>
              <div class="w-[100%] mt-15px">
                <BaseButton class="w-[100%] auth-secondary-button" onClick={toRegister}>
                  {t('login.register')}
                </BaseButton>
              </div>
            </>
          )
        }
      }
    }
  }
])

const remember = ref(userStore.getRememberMe)

const errorMessage = ref('')

const initLoginInfo = () => {
  const savedUsername = userStore.getLoginInfo
  if (savedUsername && unref(remember)) {
    setValues({ username: savedUsername })
  }
}
onMounted(() => {
  initLoginInfo()
})

const { formRegister, formMethods } = useForm()
const { getFormData, getElFormExpose, setValues } = formMethods

const loading = ref(false)

const redirect = ref<string>('')

watch(
  () => currentRoute.value,
  (route: RouteLocationNormalizedLoaded) => {
    redirect.value = route?.query?.redirect as string
  },
  {
    immediate: true
  }
)

watch(
  () => remember.value,
  (newVal) => {
    userStore.setRememberMe(newVal)
    if (!newVal) {
      userStore.setLoginInfo(undefined)
    }
  }
)

// 登录
const signIn = async () => {
  const formRef = await getElFormExpose()
  await formRef?.validate(async (isValid) => {
    if (isValid) {
      loading.value = true
      errorMessage.value = ''
      const formData = await getFormData<UserLoginType>()

      try {
        const res = await loginApi(formData)

        if (res) {
          // 是否记住我 - 只保存用户名
          if (unref(remember)) {
            userStore.setLoginInfo(formData.username)
          } else {
            userStore.setLoginInfo(undefined)
          }
          userStore.setRememberMe(unref(remember))
          const loginResult = res.data
          userStore.setToken(loginResult.token ? `Bearer ${loginResult.token}` : '')
          userStore.setUserInfo(loginResult.user)
          if (loginResult.user.mustChangePassword) {
            await push('/change-password')
            return
          }
          // 是否使用动态路由
          if (appStore.getDynamicRouter) {
            getRole()
          } else {
            await permissionStore
              .generateRoutes('static', undefined, loginResult.user.role)
              .catch(() => {})
            permissionStore.getAddRouters.forEach((route) => {
              addRoute(route as RouteRecordRaw) // 动态添加可访问路由表
            })
            permissionStore.setIsAddRouters(true)
            push({
              path: resolveRoleEntryPath(
                loginResult.user.role,
                redirect.value || loginResult.defaultPath
              )
            })
          }
        }
      } catch (error: any) {
        errorMessage.value = error?.message || '登录失败，请检查用户名和密码'
      } finally {
        loading.value = false
      }
    }
  })
}

// 获取角色信息
const getRole = async () => {
  const formData = await getFormData<UserLoginType>()
  const params = {
    roleName: formData.username
  }
  const res =
    appStore.getDynamicRouter && appStore.getServerDynamicRouter
      ? await getAdminRoleApi(params)
      : await getTestRoleApi(params)
  if (res) {
    const routers = res.data || []
    userStore.setRoleRouters(routers)
    appStore.getDynamicRouter && appStore.getServerDynamicRouter
      ? await permissionStore.generateRoutes('server', routers).catch(() => {})
      : await permissionStore.generateRoutes('frontEnd', routers).catch(() => {})

    permissionStore.getAddRouters.forEach((route) => {
      addRoute(route as RouteRecordRaw) // 动态添加可访问路由表
    })
    permissionStore.setIsAddRouters(true)
    push({
      path: resolveRoleEntryPath(
        userStore.getUserInfo?.role,
        redirect.value || userStore.getUserInfo?.defaultPath || permissionStore.addRouters[0].path
      )
    })
  }
}

// 去注册页面
const toRegister = () => {
  emit('to-register')
}
</script>

<template>
  <Form
    :schema="schema"
    :rules="rules"
    label-position="top"
    hide-required-asterisk
    size="large"
    class="auth-form dark:(border-1 border-[var(--el-border-color)] border-solid)"
    @register="formRegister"
  />
</template>
