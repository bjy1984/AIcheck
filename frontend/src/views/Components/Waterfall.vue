<script setup lang="ts">
import { Waterfall } from '@/components/Waterfall'
import { ContentWrap } from '@/components/ContentWrap'
import { useI18n } from '@/hooks/web/useI18n'
import { ref, unref } from 'vue'
import { toAnyString } from '@/utils'

const data = ref<any>([])

const getList = () => {
  const list: any = []
  for (let i = 0; i < 20; i++) {
    const height = Math.floor(Math.random() * 401) + 100
    const width = Math.floor(Math.random() * 401) + 100
    const id = toAnyString()
    list.push({
      width,
      height,
      id,
      image_uri: `https://picsum.photos/seed/${encodeURIComponent(id)}/${width}/${height}`
    })
  }
  data.value = [...unref(data), ...list]
  if (unref(data).length >= 60) {
    end.value = true
  }
}
getList()

const { t } = useI18n()

const loading = ref(false)

const end = ref(false)

const loadMore = () => {
  loading.value = true
  setTimeout(() => {
    getList()
    loading.value = false
  }, 1000)
}
</script>

<template>
  <ContentWrap :title="t('router.waterfall')">
    <Waterfall
      :data="data"
      :loading="loading"
      :end="end"
      :props="{
        src: 'image_uri',
        height: 'height'
      }"
      @load-more="loadMore"
    />
  </ContentWrap>
</template>
