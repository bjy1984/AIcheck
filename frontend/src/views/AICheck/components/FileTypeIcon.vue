<script setup lang="ts">
import { computed } from 'vue'
import { ElIcon } from 'element-plus'
import {
  DataAnalysis,
  Document,
  Files,
  Film,
  Folder,
  Memo,
  Picture,
  Postcard
} from '@element-plus/icons-vue'

type FileVisualKind =
  | 'pdf'
  | 'word'
  | 'spreadsheet'
  | 'presentation'
  | 'image'
  | 'archive'
  | 'certificate'
  | 'drawing'
  | 'report'
  | 'document'

const props = defineProps<{
  fileName: string
  fileType?: string | null
  category?: string | null
}>()

const iconByKind = {
  pdf: Document,
  word: Document,
  spreadsheet: DataAnalysis,
  presentation: Film,
  image: Picture,
  archive: Folder,
  certificate: Postcard,
  drawing: Files,
  report: Memo,
  document: Document
} as const

const kind = computed<FileVisualKind>(() => {
  const name = props.fileName.toLowerCase()
  const type = String(props.fileType || '').toLowerCase()
  const category = String(props.category || '').toLowerCase()
  const extension = name.match(/\.([a-z0-9]+)(?:[?#].*)?$/)?.[1] || ''

  if (extension === 'pdf' || type.includes('pdf')) return 'pdf'
  if (['doc', 'docx', 'odt', 'rtf', 'txt'].includes(extension) || /word|text/.test(type)) {
    return 'word'
  }
  if (['xls', 'xlsx', 'csv', 'ods'].includes(extension) || /excel|spreadsheet|csv/.test(type)) {
    return 'spreadsheet'
  }
  if (['ppt', 'pptx', 'odp'].includes(extension) || /powerpoint|presentation/.test(type)) {
    return 'presentation'
  }
  if (
    ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'tif', 'tiff'].includes(extension) ||
    type.startsWith('image/')
  ) {
    return 'image'
  }
  if (
    ['zip', 'rar', '7z', 'tar', 'gz'].includes(extension) ||
    /zip|archive|compressed/.test(type)
  ) {
    return 'archive'
  }

  const businessLabel = `${name} ${category}`
  if (/资质|资格|许可证|许可资质|执照|证书|核准/.test(businessLabel)) return 'certificate'
  if (/设计|图纸|施工图|竣工图|蓝图/.test(businessLabel)) return 'drawing'
  if (/报告|记录|证明|方案|规程|工艺|评定|检验|检测|试验/.test(businessLabel)) {
    return 'report'
  }
  return 'document'
})

const icon = computed(() => iconByKind[kind.value])
</script>

<template>
  <ElIcon :class="['file-type-icon', `is-${kind}`]" :data-file-kind="kind" aria-hidden="true">
    <component :is="icon" />
  </ElIcon>
</template>

<style scoped>
.file-type-icon {
  display: inline-flex;
  width: 22px;
  height: 22px;
  font-size: 14px;
  color: #52647d;
  background: #f1f5f9;
  border-radius: 6px;
  flex: 0 0 22px;
}

.file-type-icon.is-pdf {
  color: #b42318;
  background: #fff1f0;
}

.file-type-icon.is-word,
.file-type-icon.is-drawing {
  color: #1f66d8;
  background: #edf5ff;
}

.file-type-icon.is-spreadsheet {
  color: #087443;
  background: #ecfdf3;
}

.file-type-icon.is-presentation,
.file-type-icon.is-report {
  color: #9a4d00;
  background: #fff6e8;
}

.file-type-icon.is-image {
  color: #6941c6;
  background: #f4f0ff;
}

.file-type-icon.is-archive,
.file-type-icon.is-certificate {
  color: #0e7490;
  background: #ecfeff;
}
</style>
