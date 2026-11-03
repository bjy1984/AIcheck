<script setup lang="ts">
import UserFeedbackLauncher from '@/views/AICheck/components/UserFeedbackLauncher.vue'
</script>

<template>
  <RouterView />
  <!-- 意见反馈：所有工作台和后台页面共用这个布局，挂在这里每个角色都能看到 -->
  <UserFeedbackLauncher />
</template>
