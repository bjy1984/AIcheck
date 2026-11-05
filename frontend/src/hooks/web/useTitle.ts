import { watch, ref } from 'vue'
import { isString } from '@/utils/is'
import { useAppStoreWithOut } from '@/store/modules/app'
import { useI18n } from '@/hooks/web/useI18n'
import { useUserStoreWithOut } from '@/store/modules/user'
import { appTitleFor } from '@/utils/reviewerWording'

export const useTitle = (newTitle?: string) => {
  const { t } = useI18n()
  const appStore = useAppStoreWithOut()
  // 登录页和施工方、无损检测、建设方用对外名字，不带「AI」（utils/reviewerWording）
  const appTitle = appTitleFor(useUserStoreWithOut().getUserInfo?.role, appStore.getTitle)

  const title = ref(newTitle ? `${appTitle} - ${t(newTitle as string)}` : appTitle)

  watch(
    title,
    (n, o) => {
      if (isString(n) && n !== o && document) {
        document.title = n
      }
    },
    { immediate: true }
  )

  return title
}
