<script setup lang="ts">
import UserFeedbackLauncher from '@/views/AICheck/components/UserFeedbackLauncher.vue'
import GuideSpotlight from '@/views/AICheck/userGuide/GuideSpotlight.vue'
import UserGuideDrawer from '@/views/AICheck/userGuide/UserGuideDrawer.vue'
</script>

<template>
  <RouterView />
  <!-- 意见反馈：所有工作台和后台页面共用这个布局，挂在这里每个角色都能看到 -->
  <UserFeedbackLauncher />
  <!-- 使用帮助：账号菜单「使用帮助」打开；「带我去」和「开始引导」的高亮层 -->
  <UserGuideDrawer />
  <GuideSpotlight />
</template>
