<script setup lang="ts">
import { Error } from '@/components/Error'
import { useUserStore } from '@/store/modules/user'
import { getRoleDefaultPath } from '@/utils/roleAccess'
import { useRouter } from 'vue-router'

const { push } = useRouter()
const userStore = useUserStore()

const errorClick = () => {
  push(getRoleDefaultPath(userStore.getUserInfo?.role) || '/')
}
</script>

<template>
  <Error @error-click="errorClick" />
</template>
